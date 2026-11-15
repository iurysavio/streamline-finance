"""Local FastAPI boundary. Business rules stay in domain/importer/repository modules."""

from __future__ import annotations

from calendar import monthrange
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from streamline_finance.categorization import (
    CategorizationRule,
    suggest_category,
)
from streamline_finance.domain import Category, MovementType, Person, SourceKind
from streamline_finance.importers.nubank import ImportPreview, preview_nubank_csv
from streamline_finance.rules import HistoricalRuleError, load_expense_rules
from streamline_finance.storage import (
    FinanceRepository,
    ImportConflictError,
    ImportRejectedError,
    MatchDecision,
)
from streamline_finance.ui_summary import (
    build_spending_summary,
    build_spending_trend,
    compare_spending_periods,
    format_brl,
    top_expenses,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class ApiMessage(BaseModel):
    detail: str


class PreviewErrorResponse(BaseModel):
    code: str
    message: str
    line_number: int | None


class PreviewTransactionResponse(BaseModel):
    transaction_id: str
    description: str
    amount_minor_units: int
    currency: str
    movement_type: str
    person: str
    source_kind: str
    occurred_on: str
    source_fields: dict[str, str]


class PreviewResponse(BaseModel):
    can_confirm: bool
    transaction_count: int
    transactions: list[PreviewTransactionResponse]
    errors: list[PreviewErrorResponse]
    skipped_blank_lines: list[int]


class ImportConfirmationResponse(BaseModel):
    batch_id: int
    imported_count: int
    duplicate_count: int
    already_imported: bool


class TransactionResponse(BaseModel):
    transaction_id: str
    source_key: str
    description: str
    amount_minor_units: int
    currency: str
    movement_type: str
    person: str
    source_kind: str
    occurred_on: str
    posted_on: str | None
    category: dict[str, str] | None


class TransactionsResponse(BaseModel):
    transactions: list[TransactionResponse]


class MovementReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    movement_type: MovementType
    confirmed: bool
    macro: str | None = Field(default=None, min_length=1, max_length=120)
    micro: str | None = Field(default=None, min_length=1, max_length=120)


class CategoryReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    macro: str = Field(min_length=1, max_length=120)
    micro: str = Field(min_length=1, max_length=120)
    confirmed: bool


class CategorizationRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=300)
    macro: str = Field(min_length=1, max_length=120)
    micro: str = Field(min_length=1, max_length=120)


class CategorySuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[CategorizationRuleRequest] = Field(default_factory=list, max_length=500)


class CategorySuggestionResponse(BaseModel):
    status: str
    suggested_category: dict[str, str] | None
    matched_rule_ids: list[str]
    explanation: str


class HistoricalRuleResponse(BaseModel):
    rule_id: str
    description: str
    macro: str
    micro: str


class HistoricalRulesPreviewResponse(BaseModel):
    rules: list[HistoricalRuleResponse]
    rule_count: int
    skipped_without_description: int
    skipped_incomplete_categories: int
    excluded_descriptions: list[str]


class PaymentDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: MatchDecision
    confirmed: bool


class PaymentCandidateResponse(BaseModel):
    candidate_id: int
    expense_transaction_id: str
    payment_transaction_id: str
    amount_minor_units: int
    day_difference: int
    status: str


class PaymentCandidatesResponse(BaseModel):
    candidates: list[PaymentCandidateResponse]


class PersonTotalResponse(BaseModel):
    person: str
    amount_minor_units: int
    formatted_brl: str


class CategoryTotalResponse(BaseModel):
    macro: str
    micro: str
    amount_minor_units: int
    formatted_brl: str


class MonthlySummaryResponse(BaseModel):
    month: str
    person_filter: str | None
    total_minor_units: int
    formatted_brl: str
    transaction_count: int
    by_person: list[PersonTotalResponse]
    by_category: list[CategoryTotalResponse]


class SpendingTrendPointResponse(BaseModel):
    period: str
    group: str
    amount_minor_units: int
    formatted_brl: str


class SpendingTrendResponse(BaseModel):
    start: str
    end: str
    granularity: str
    dimension: str
    points: list[SpendingTrendPointResponse]


class TopExpenseResponse(BaseModel):
    transaction_id: str
    occurred_on: str
    description: str
    person: str
    category_macro: str
    category_micro: str
    amount_minor_units: int
    formatted_brl: str


class TopExpensesResponse(BaseModel):
    start: str
    end: str
    limit: int
    expenses: list[TopExpenseResponse]


class PeriodComparisonResponse(BaseModel):
    current_start: str
    current_end: str
    previous_start: str
    previous_end: str
    current_total_minor_units: int
    current_total_brl: str
    previous_total_minor_units: int
    previous_total_brl: str
    variation_minor_units: int
    variation_brl: str
    variation_percent: float | None


class UncategorizedResponse(BaseModel):
    count: int
    transaction_ids: list[str]


class UncategorizedCountResponse(BaseModel):
    count: int


class ImportRecordResponse(BaseModel):
    batch_id: int
    source_key: str
    imported_at: str
    row_count: int
    person: str
    source_kind: str


class ImportsResponse(BaseModel):
    imports: list[ImportRecordResponse]


def create_app(
    *,
    repository: FinanceRepository | None = None,
    data_root: str | Path = "data",
) -> FastAPI:
    """Create API; default repository is opened only during app lifespan, never at import."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_repository = repository is None
        app.state.repository = repository or FinanceRepository(
            Path(data_root) / "db" / "finance.sqlite3"
        )
        try:
            yield
        finally:
            if owns_repository:
                app.state.repository.close()

    app = FastAPI(
        title="Streamline Finance Local API",
        version="0.1.0",
        description="API local para revisar e importar dados financeiros privados.",
        lifespan=lifespan,
    )
    if repository is not None:
        app.state.repository = repository

    @app.middleware("http")
    async def allow_loopback_clients_only(request: Request, call_next):
        client_host = request.client.host if request.client is not None else None
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse(
                status_code=403, content={"detail": "API aceita somente clientes locais"}
            )
        return await call_next(request)

    @app.exception_handler(ImportConflictError)
    async def conflict_handler(_: Request, exc: ImportConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ImportRejectedError)
    async def rejected_handler(_: Request, exc: ImportRejectedError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def get_repository(request: Request) -> FinanceRepository:
        return request.app.state.repository

    async def read_upload(file: UploadFile) -> bytes:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Arquivo excede o limite local de 10 MiB")
        return content

    def parse_preview(
        content: bytes,
        source_key: str,
        person: Person,
        source_kind: SourceKind,
    ) -> ImportPreview:
        return preview_nubank_csv(
            content,
            source_key=source_key,
            person=person,
            source_kind=source_kind,
        )

    @app.get("/health", response_model=ApiMessage)
    def health() -> ApiMessage:
        return ApiMessage(detail="local api ready")

    @app.get("/", response_model=ApiMessage)
    def root() -> ApiMessage:
        return ApiMessage(detail="Streamline Finance API local. Abra /docs para explorar as rotas.")

    @app.get("/openapi.json", include_in_schema=False)
    def openapi_documentation(request: Request):
        """Expose schema to local docs without advertising the broader OpenAPI endpoint."""
        return request.app.openapi()

    @app.middleware("http")
    async def protect_sensitive_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(
            ("/imports", "/transactions", "/payment-candidates", "/categories")
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.middleware("http")
    async def reject_cross_site_mutations(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin is not None:
                from urllib.parse import urlparse

                parsed_origin = urlparse(origin)
                request_host = request.headers.get("host", "")
                if parsed_origin.netloc != request_host:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "Cross-origin writes are not accepted by this local API"
                        },
                    )
        return await call_next(request)

    @app.post("/imports/preview", response_model=PreviewResponse)
    async def preview_import(
        file: Annotated[UploadFile, File()],
        source_key: Annotated[str, Form(min_length=1, max_length=100)],
        person: Annotated[Person, Form()],
        source_kind: Annotated[SourceKind, Form()] = SourceKind.BANK_ACCOUNT,
    ) -> PreviewResponse:
        content = await read_upload(file)
        preview = parse_preview(content, source_key, person, source_kind)
        return _preview_response(preview)

    @app.post("/imports/confirm", response_model=ImportConfirmationResponse)
    async def confirm_import(
        request: Request,
        response: Response,
        file: Annotated[UploadFile, File()],
        source_key: Annotated[str, Form(min_length=1, max_length=100)],
        person: Annotated[Person, Form()],
        confirmed: Annotated[bool, Form()],
        source_kind: Annotated[SourceKind, Form()] = SourceKind.BANK_ACCOUNT,
    ) -> ImportConfirmationResponse:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Importação não gravada. Confira a prévia e confirme explicitamente.",
            )
        content = await read_upload(file)
        preview = parse_preview(content, source_key, person, source_kind)
        if not preview.can_confirm:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Importação recusada; corrija os erros da prévia.",
                    "errors": [
                        error.model_dump(mode="json") for error in _preview_response(preview).errors
                    ],
                },
            )
        try:
            result = get_repository(request).confirm_import(
                preview,
                source_key=source_key,
                content=content,
            )
        except (ValueError, ImportRejectedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        response.status_code = 200 if result.already_imported else 201
        return ImportConfirmationResponse(
            batch_id=result.batch_id,
            imported_count=result.imported_count,
            duplicate_count=result.duplicate_count,
            already_imported=result.already_imported,
        )

    @app.get("/imports", response_model=ImportsResponse)
    def list_imports(request: Request) -> ImportsResponse:
        imports = get_repository(request).list_imports()
        return ImportsResponse(
            imports=[
                ImportRecordResponse(
                    batch_id=row.batch_id,
                    source_key=row.source_key,
                    imported_at=row.imported_at,
                    row_count=row.row_count,
                    person=row.person.value,
                    source_kind=row.source_kind.value,
                )
                for row in imports
            ]
        )

    @app.get("/transactions", response_model=TransactionsResponse)
    def list_transactions(
        request: Request,
        source_key: Annotated[str | None, Query(max_length=100)] = None,
        person: Person | None = None,
        movement_type: MovementType | None = None,
        uncategorized_only: bool = False,
    ) -> TransactionsResponse:
        transactions = get_repository(request).list_transactions()
        filtered = [
            transaction
            for transaction in transactions
            if (source_key is None or transaction.source_key == source_key)
            and (person is None or transaction.person is person)
            and (movement_type is None or transaction.movement_type is movement_type)
            and (
                not uncategorized_only
                or (
                    transaction.movement_type is MovementType.EXPENSE
                    and transaction.category is None
                )
            )
        ]
        return TransactionsResponse(transactions=[_transaction_response(row) for row in filtered])

    @app.get("/transactions/{source_key}/{transaction_id}", response_model=TransactionResponse)
    def get_transaction(
        request: Request,
        source_key: str,
        transaction_id: str,
    ) -> TransactionResponse:
        try:
            transaction = get_repository(request).get_transaction(
                transaction_id, source_key=source_key
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Transação não encontrada") from exc
        return _transaction_response(transaction)

    @app.post(
        "/transactions/{source_key}/{transaction_id}/movement-type",
        response_model=TransactionResponse,
    )
    def review_movement_type(
        request: Request,
        source_key: str,
        transaction_id: str,
        body: MovementReviewRequest,
    ) -> TransactionResponse:
        if not body.confirmed:
            raise HTTPException(status_code=409, detail="Confirmação explícita é necessária")
        if (body.macro is None) != (body.micro is None):
            raise HTTPException(status_code=422, detail="Forneça macro e micro categoria juntos")
        try:
            row = get_repository(request).review_movement_type(
                source_key,
                transaction_id,
                body.movement_type,
                confirm=True,
                category=(
                    Category(body.macro.strip(), body.micro.strip())
                    if body.macro is not None and body.micro is not None
                    else None
                ),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Transação não encontrada") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _transaction_response(row)

    @app.post(
        "/transactions/{source_key}/{transaction_id}/category-suggestion",
        response_model=CategorySuggestionResponse,
    )
    def suggest_transaction_category(
        request: Request,
        source_key: str,
        transaction_id: str,
        body: CategorySuggestionRequest,
    ) -> CategorySuggestionResponse:
        repository = get_repository(request)
        try:
            stored = repository.get_transaction(transaction_id, source_key=source_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Transação não encontrada") from exc
        transaction = _domain_transaction(stored)
        rules = _categorization_rules(body.rules)
        result = suggest_category(transaction, rules)
        return CategorySuggestionResponse(
            status=result.status.value,
            suggested_category=_category_response(result.suggested_category),
            matched_rule_ids=list(result.matched_rule_ids),
            explanation=result.explanation,
        )

    @app.get("/categories")
    def list_categories(request: Request):
        return {
            "categories": [
                _category_response(category)
                for category in get_repository(request).list_categories()
            ]
        }

    @app.post("/categories")
    def add_category(request: Request, body: CategoryReviewRequest):
        if not body.confirmed:
            raise HTTPException(status_code=409, detail="Confirmação explícita é necessária")
        try:
            get_repository(request).add_category(Category(body.macro, body.micro))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"detail": "Categoria cadastrada"}

    @app.post(
        "/categories/historical-rules/preview",
        response_model=HistoricalRulesPreviewResponse,
    )
    async def preview_historical_rules(
        file: Annotated[UploadFile, File()],
        confirm_column_mapping: Annotated[bool, Form()],
    ) -> HistoricalRulesPreviewResponse:
        content = await read_upload(file)
        try:
            loaded = load_expense_rules(
                content,
                confirm_column_mapping=confirm_column_mapping,
            )
        except HistoricalRuleError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return HistoricalRulesPreviewResponse(
            rules=[
                HistoricalRuleResponse(
                    rule_id=rule.rule_id,
                    description=rule.description,
                    macro=rule.category.macro,
                    micro=rule.category.micro,
                )
                for rule in loaded.rules
            ],
            rule_count=loaded.rule_count,
            skipped_without_description=loaded.skipped_without_description,
            skipped_incomplete_categories=loaded.skipped_incomplete_categories,
            excluded_descriptions=list(loaded.excluded_descriptions),
        )

    @app.post(
        "/transactions/{source_key}/{transaction_id}/category",
        response_model=TransactionResponse,
    )
    def confirm_transaction_category(
        request: Request,
        source_key: str,
        transaction_id: str,
        body: CategoryReviewRequest,
    ) -> TransactionResponse:
        if not body.confirmed:
            raise HTTPException(status_code=409, detail="Confirmação explícita é necessária")
        try:
            row = get_repository(request).confirm_category(
                source_key,
                transaction_id,
                Category(body.macro.strip(), body.micro.strip()),
                confirm=True,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Transação não encontrada") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _transaction_response(row)

    @app.post(
        "/transactions/{source_key}/{transaction_id}/category-suggestion/confirm",
        response_model=TransactionResponse,
    )
    def confirm_transaction_suggestion(
        request: Request,
        source_key: str,
        transaction_id: str,
        body: CategoryReviewRequest,
    ) -> TransactionResponse:
        return confirm_transaction_category(request, source_key, transaction_id, body)

    @app.get("/reports/monthly-spending", response_model=MonthlySummaryResponse)
    def monthly_spending(
        request: Request,
        month: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")],
        person: Person | None = None,
    ) -> MonthlySummaryResponse:
        year, month_number = (int(part) for part in month.split("-"))
        if not 1 <= month_number <= 12:
            raise HTTPException(status_code=422, detail="Mês deve estar entre 01 e 12")
        # Validate calendar month and preserve project date meaning (date-only, no timezone shift).
        date(year, month_number, monthrange(year, month_number)[1])
        summary = build_spending_summary(
            get_repository(request).list_transactions(),
            month=month,
            person=person.value if person is not None else None,
        )
        return MonthlySummaryResponse(
            month=summary.month,
            person_filter=person.value if person is not None else None,
            total_minor_units=summary.total_minor_units,
            formatted_brl=format_brl(summary.total_minor_units),
            transaction_count=summary.transaction_count,
            by_person=[
                PersonTotalResponse(
                    person=name,
                    amount_minor_units=value,
                    formatted_brl=format_brl(value),
                )
                for name, value in sorted(summary.by_person.items())
            ],
            by_category=[
                CategoryTotalResponse(
                    macro=macro,
                    micro=micro,
                    amount_minor_units=value,
                    formatted_brl=format_brl(value),
                )
                for (macro, micro), value in sorted(summary.by_category.items())
            ],
        )

    @app.get("/reports/spending-trend", response_model=SpendingTrendResponse)
    def spending_trend(
        request: Request,
        start: Annotated[date, Query()],
        end: Annotated[date, Query()],
        granularity: Annotated[str, Query(pattern="^(day|week|month)$")],
        dimension: Annotated[str, Query(pattern="^(total|person|macro|micro)$")],
        person: Person | None = None,
    ) -> SpendingTrendResponse:
        if start > end:
            raise HTTPException(status_code=422, detail="Data inicial deve ser anterior à final")
        transactions = get_repository(request).list_transactions()
        if person is not None:
            transactions = tuple(row for row in transactions if row.person is person)
        points = build_spending_trend(
            transactions,
            start=start,
            end=end,
            granularity=granularity,
            dimension=dimension,
        )
        return SpendingTrendResponse(
            start=start.isoformat(),
            end=end.isoformat(),
            granularity=granularity,
            dimension=dimension,
            points=[
                SpendingTrendPointResponse(
                    period=point.period,
                    group=point.group,
                    amount_minor_units=point.amount_minor_units,
                    formatted_brl=format_brl(point.amount_minor_units),
                )
                for point in points
            ],
        )

    @app.get("/reports/top-expenses", response_model=TopExpensesResponse)
    def report_top_expenses(
        request: Request,
        start: Annotated[date, Query()],
        end: Annotated[date, Query()],
        person: Person | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> TopExpensesResponse:
        if start > end:
            raise HTTPException(status_code=422, detail="Data inicial deve ser anterior à final")
        transactions = get_repository(request).list_transactions()
        expenses = top_expenses(
            transactions,
            start=start,
            end=end,
            person=person.value if person else None,
            limit=limit,
        )
        return TopExpensesResponse(
            start=start.isoformat(),
            end=end.isoformat(),
            limit=limit,
            expenses=[
                TopExpenseResponse(
                    transaction_id=row.transaction_id,
                    occurred_on=row.occurred_on.isoformat(),
                    description=row.description,
                    person=row.person,
                    category_macro=row.category_macro,
                    category_micro=row.category_micro,
                    amount_minor_units=row.amount_minor_units,
                    formatted_brl=format_brl(row.amount_minor_units),
                )
                for row in expenses
            ],
        )

    @app.get("/reports/period-comparison", response_model=PeriodComparisonResponse)
    def report_period_comparison(
        request: Request,
        start: Annotated[date, Query()],
        end: Annotated[date, Query()],
        person: Person | None = None,
    ) -> PeriodComparisonResponse:
        if start > end:
            raise HTTPException(status_code=422, detail="Data inicial deve ser anterior à final")
        comparison = compare_spending_periods(
            get_repository(request).list_transactions(),
            start=start,
            end=end,
            person=person.value if person else None,
        )
        return PeriodComparisonResponse(
            current_start=comparison.current_start.isoformat(),
            current_end=comparison.current_end.isoformat(),
            previous_start=comparison.previous_start.isoformat(),
            previous_end=comparison.previous_end.isoformat(),
            current_total_minor_units=comparison.current_total_minor_units,
            current_total_brl=format_brl(comparison.current_total_minor_units),
            previous_total_minor_units=comparison.previous_total_minor_units,
            previous_total_brl=format_brl(comparison.previous_total_minor_units),
            variation_minor_units=comparison.variation_minor_units,
            variation_brl=format_brl(comparison.variation_minor_units),
            variation_percent=comparison.variation_percent,
        )

    @app.get("/transactions/uncategorized", response_model=UncategorizedCountResponse)
    def list_uncategorized_expenses(
        request: Request,
        start: date | None = None,
        end: date | None = None,
        person: Person | None = None,
    ) -> UncategorizedCountResponse:
        if (start is None) != (end is None):
            raise HTTPException(status_code=422, detail="Informe data inicial e final juntas")
        if start is not None and end is not None and start > end:
            raise HTTPException(status_code=422, detail="Data inicial deve ser anterior à final")
        transactions = get_repository(request).list_transactions()
        uncategorized = [
            row
            for row in transactions
            if row.movement_type is MovementType.EXPENSE
            and row.category is None
            and (start is None or row.occurred_on >= start)
            and (end is None or row.occurred_on <= end)
            and (person is None or row.person is person)
        ]
        return UncategorizedCountResponse(count=len(uncategorized))

    @app.post("/payment-candidates/refresh", response_model=PaymentCandidatesResponse)
    def refresh_payment_candidates(
        request: Request,
        window_days: Annotated[int, Query(ge=0, le=60)] = 5,
    ) -> PaymentCandidatesResponse:
        candidates = get_repository(request).refresh_payment_candidates(window_days=window_days)
        return PaymentCandidatesResponse(
            candidates=[_candidate_response(candidate) for candidate in candidates]
        )

    @app.get("/payment-candidates", response_model=PaymentCandidatesResponse)
    def list_payment_candidates(request: Request) -> PaymentCandidatesResponse:
        candidates = get_repository(request).list_payment_candidates()
        return PaymentCandidatesResponse(
            candidates=[_candidate_response(candidate) for candidate in candidates]
        )

    @app.post(
        "/payment-candidates/{candidate_id}/decision", response_model=PaymentCandidateResponse
    )
    def decide_payment_candidate(
        request: Request,
        candidate_id: int,
        body: PaymentDecisionRequest,
    ) -> PaymentCandidateResponse:
        if not body.confirmed:
            raise HTTPException(status_code=409, detail="Confirmação explícita é necessária")
        try:
            candidate = get_repository(request).decide_payment_candidate(
                candidate_id, body.decision
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Candidato não encontrado") from exc
        return _candidate_response(candidate)

    return app


def _preview_response(preview: ImportPreview) -> PreviewResponse:
    return PreviewResponse(
        can_confirm=preview.can_confirm,
        transaction_count=len(preview.transactions),
        transactions=[
            PreviewTransactionResponse(
                transaction_id=row.transaction.transaction_id,
                description=row.transaction.description,
                amount_minor_units=row.transaction.amount.minor_units,
                currency=row.transaction.amount.currency,
                movement_type=row.transaction.movement_type.value,
                person=row.transaction.person.value,
                source_kind=row.transaction.source_kind.value,
                occurred_on=row.transaction.occurred_on.isoformat(),
                source_fields=dict(row.source_fields),
            )
            for row in preview.transactions
        ],
        errors=[
            PreviewErrorResponse(
                code=error.code.value,
                message=error.message,
                line_number=error.line_number,
            )
            for error in preview.errors
        ],
        skipped_blank_lines=list(preview.skipped_blank_lines),
    )


def _transaction_response(transaction) -> TransactionResponse:
    return TransactionResponse(
        transaction_id=transaction.transaction_id,
        source_key=transaction.source_key,
        description=transaction.description,
        amount_minor_units=transaction.amount_minor_units,
        currency=transaction.currency,
        movement_type=transaction.movement_type.value,
        person=transaction.person.value,
        source_kind=transaction.source_kind.value,
        occurred_on=transaction.occurred_on.isoformat(),
        posted_on=transaction.posted_on.isoformat() if transaction.posted_on else None,
        category=_category_response(transaction.category),
    )


def _category_response(category: Category | None) -> dict[str, str] | None:
    if category is None:
        return None
    return {"macro": category.macro, "micro": category.micro}


def _candidate_response(candidate) -> PaymentCandidateResponse:
    return PaymentCandidateResponse(
        candidate_id=candidate.candidate_id,
        expense_transaction_id=candidate.expense_transaction_id,
        payment_transaction_id=candidate.payment_transaction_id,
        amount_minor_units=candidate.amount_minor_units,
        day_difference=candidate.day_difference,
        status=candidate.status.value,
    )


def _domain_transaction(stored):
    from streamline_finance.domain import Money, Transaction

    return Transaction(
        transaction_id=stored.transaction_id,
        description=stored.description,
        amount=Money(stored.amount_minor_units, stored.currency),
        movement_type=stored.movement_type,
        person=stored.person,
        occurred_on=stored.occurred_on,
        posted_on=stored.posted_on,
        category=stored.category,
        source_key=stored.source_key,
        source_kind=stored.source_kind,
    )


def _categorization_rules(
    payload: list[CategorizationRuleRequest],
) -> list[CategorizationRule]:
    rules: list[CategorizationRule] = []
    for item in payload:
        rules.append(
            CategorizationRule(
                rule_id=item.rule_id,
                description=item.description,
                category=Category(macro=item.macro, micro=item.micro),
            )
        )
    return rules


app = create_app()
