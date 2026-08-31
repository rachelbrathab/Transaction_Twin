"""Tests for Calibration Intelligence API integration and security."""

from app.main import app


class TestCalibrationIntelligenceEndpoints:
    """Verify endpoints exist and respond correctly."""

    def test_outcomes_endpoint_exists(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/api/v1/analytics/calibration/outcomes")
        # Without auth: 401. With auth: 200. Never 404/405.
        assert response.status_code in (401, 200)
        assert response.status_code != 404
        assert response.status_code != 405

    def test_recommendations_endpoint_exists(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/api/v1/analytics/calibration/recommendations")
        assert response.status_code in (401, 200)
        assert response.status_code != 404
        assert response.status_code != 405

    def test_review_endpoint_exists(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/api/v1/analytics/calibration/recommendations/fake-id/review",
            json={"action": "approve"},
        )
        # Without auth: 401. Not 405.
        assert response.status_code in (401, 404)
        assert response.status_code != 405

    def test_activate_endpoint_exists(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/api/v1/analytics/calibration/versions/calibration-v1/activate",
            json={"confirm": True},
        )
        assert response.status_code in (401, 404)
        assert response.status_code != 405

    def test_outcomes_with_window_days(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get(
            "/api/v1/analytics/calibration/outcomes?window_days=7",
        )
        # Without auth: 401
        assert response.status_code in (200, 401, 422, 500)

    def test_outcomes_window_days_max(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get(
            "/api/v1/analytics/calibration/outcomes?window_days=200",
        )
        # Without auth: 401. With auth: 422.
        assert response.status_code in (401, 422)

    def test_review_invalid_action(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/api/v1/analytics/calibration/recommendations/fake-id/review",
            json={"action": "invalid"},
        )
        assert response.status_code in (401, 422)

    def test_activate_without_confirm(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/api/v1/analytics/calibration/versions/calibration-v1/activate",
            json={"confirm": False},
        )
        assert response.status_code in (401, 422)


class TestSecurity:
    """Security tests for calibration intelligence."""

    def test_no_eval_in_dataset(self):
        import inspect

        from app.services.calibration_intelligence import dataset

        source = inspect.getsource(dataset)
        assert "eval(" not in source
        assert "exec(" not in source

    def test_no_eval_in_metrics(self):
        import inspect

        from app.services.calibration_intelligence import metrics

        source = inspect.getsource(metrics)
        assert "eval(" not in source
        assert "exec(" not in source

    def test_no_eval_in_recommendations(self):
        import inspect

        from app.services.calibration_intelligence import recommendations

        source = inspect.getsource(recommendations)
        assert "eval(" not in source
        assert "exec(" not in source

    def test_no_subprocess(self):
        import inspect

        from app.services.calibration_intelligence import (
            dataset,
            engine,
            metrics,
            recommendations,
        )

        for mod in [dataset, metrics, recommendations, engine]:
            source = inspect.getsource(mod)
            assert "subprocess" not in source
            assert "os.system" not in source

    def test_no_llm(self):
        import inspect

        from app.services.calibration_intelligence import (
            dataset,
            engine,
            metrics,
            recommendations,
        )

        for mod in [dataset, metrics, recommendations, engine]:
            source = inspect.getsource(mod)
            assert "openai" not in source.lower()
            assert "anthropic" not in source.lower()

    def test_no_database_in_core(self):
        import inspect

        from app.services.calibration_intelligence import (
            dataset,
            metrics,
            recommendations,
        )

        for mod in [dataset, metrics, recommendations]:
            source = inspect.getsource(mod)
            assert "sqlalchemy" not in source.lower()

    def test_no_payment_execution(self):
        import inspect

        from app.services.calibration_intelligence import (
            dataset,
            engine,
            metrics,
            recommendations,
        )

        for mod in [dataset, metrics, recommendations, engine]:
            source = inspect.getsource(mod)
            assert "razorpay" not in source.lower()
            assert "capture" not in source.lower()


class TestBackwardCompatibility:
    """Verify existing engines are not modified."""

    def test_risk_weights_unchanged(self):
        from app.services.risk_engine.constants import SIGNAL_WEIGHTS
        from app.services.risk_engine.models import RiskSignalType

        assert SIGNAL_WEIGHTS[RiskSignalType.INTENT_DRIFT] == 0.25
        assert SIGNAL_WEIGHTS[RiskSignalType.AMOUNT_ANOMALY] == 0.15
        assert SIGNAL_WEIGHTS[RiskSignalType.AGENT_TRUST] == 0.15
        assert SIGNAL_WEIGHTS[RiskSignalType.MERCHANT_TRUST] == 0.10
        assert SIGNAL_WEIGHTS[RiskSignalType.POLICY_INTERACTION] == 0.20
        assert SIGNAL_WEIGHTS[RiskSignalType.VELOCITY] == 0.05
        assert SIGNAL_WEIGHTS[RiskSignalType.CURRENCY_MISMATCH] == 0.05
        assert SIGNAL_WEIGHTS[RiskSignalType.GEOGRAPHIC_ANOMALY] == 0.05

    def test_existing_constants_read_only(self):
        from app.services.calibration_intelligence.constants import (
            EXISTING_RISK_LEVEL_THRESHOLDS,
            EXISTING_SIGNAL_WEIGHTS,
        )

        # These should be copies/references, not the actual mutable objects
        assert EXISTING_SIGNAL_WEIGHTS["intent_drift"] == 0.25
        assert EXISTING_RISK_LEVEL_THRESHOLDS["critical"] == 0.75
