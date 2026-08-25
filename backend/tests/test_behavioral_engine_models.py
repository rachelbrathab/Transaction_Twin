"""Tests for Behavioral Engine domain models."""

from app.services.behavioral_engine.models import (
    AnomalyContext,
    AnomalyDimension,
    BehavioralAnomalyResult,
    DimensionAnomaly,
    TransactionRecord,
)


class TestAnomalyDimension:
    """Tests for AnomalyDimension enum."""

    def test_all_dimensions(self):
        assert AnomalyDimension.AMOUNT == "amount"
        assert AnomalyDimension.FREQUENCY == "frequency"
        assert AnomalyDimension.MERCHANT == "merchant"

    def test_three_dimensions(self):
        assert len(AnomalyDimension) == 3


class TestTransactionRecord:
    """Tests for TransactionRecord model."""

    def test_valid_record(self):
        record = TransactionRecord(
            transaction_id="txn-001",
            amount=1000.0,
            currency="INR",
            transaction_type="purchase",
            merchant_id="merch-001",
            created_at="2025-01-15T10:00:00Z",
        )
        assert record.amount == 1000.0
        assert record.merchant_id == "merch-001"

    def test_defaults(self):
        record = TransactionRecord(transaction_id="txn-002", amount=50.0)
        assert record.currency == "INR"
        assert record.merchant_id is None

    def test_negative_amount_rejected(self):
        import pytest
        with pytest.raises(Exception):
            TransactionRecord(transaction_id="txn-003", amount=-100.0)


class TestAnomalyContext:
    """Tests for AnomalyContext model."""

    def test_empty_context(self):
        ctx = AnomalyContext(
            agent_id="agent-001",
            user_id="user-001",
        )
        assert ctx.history_available is False
        assert len(ctx.transactions) == 0

    def test_unavailable_context(self):
        ctx = AnomalyContext(
            agent_id="agent-001",
            user_id="user-001",
            history_available=False,
        )
        assert ctx.history_available is False

    def test_full_context(self):
        ctx = AnomalyContext(
            agent_id="agent-001",
            user_id="user-001",
            transactions=[
                TransactionRecord(
                    transaction_id="txn-001",
                    amount=100.0,
                    merchant_id="merch-001",
                    created_at="2025-01-15T10:00:00Z",
                ),
            ],
            proposal_amount=200.0,
            proposal_merchant_id="merch-002",
            history_window_days=30,
        )
        assert ctx.history_window_days == 30
        assert ctx.proposal_amount == 200.0
        assert ctx.proposal_merchant_id == "merch-002"
        assert len(ctx.transactions) == 1


class TestDimensionAnomaly:
    """Tests for DimensionAnomaly model."""

    def test_valid_dimension(self):
        dim = DimensionAnomaly(
            dimension=AnomalyDimension.AMOUNT,
            score=0.5,
            confidence=0.8,
            what="Test",
            why="Test reason",
        )
        assert dim.score == 0.5
        assert dim.baseline_used == ""

    def test_score_bounds(self):
        import pytest
        with pytest.raises(Exception):
            DimensionAnomaly(
                dimension=AnomalyDimension.AMOUNT,
                score=-0.1,
                confidence=1.0,
            )
        with pytest.raises(Exception):
            DimensionAnomaly(
                dimension=AnomalyDimension.AMOUNT,
                score=1.1,
                confidence=1.0,
            )

    def test_confidence_bounds(self):
        import pytest
        with pytest.raises(Exception):
            DimensionAnomaly(
                dimension=AnomalyDimension.FREQUENCY,
                score=0.5,
                confidence=-0.1,
            )
        with pytest.raises(Exception):
            DimensionAnomaly(
                dimension=AnomalyDimension.FREQUENCY,
                score=0.5,
                confidence=1.1,
            )


class TestBehavioralAnomalyResult:
    """Tests for BehavioralAnomalyResult model."""

    def test_empty_result(self):
        result = BehavioralAnomalyResult()
        assert result.overall_score == 0.0
        assert result.confidence == 1.0
        assert result.dimension_count == 0

    def test_result_with_dimensions(self):
        dims = [
            DimensionAnomaly(
                dimension=AnomalyDimension.AMOUNT,
                score=0.3,
                confidence=0.7,
            ),
        ]
        result = BehavioralAnomalyResult(
            overall_score=0.3,
            confidence=0.7,
            dimensions=dims,
            dimension_count=1,
        )
        assert result.dimension_count == 1
        assert result.overall_score == 0.3
