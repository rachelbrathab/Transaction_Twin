# Transaction Twin — ML Module

This module will contain the machine learning components for Transaction Twin.

## Planned Components (Sprint 3+)

- Risk scoring model
- Behavioral anomaly detection
- Agent reputation scoring
- Feature engineering pipeline
- Model training and evaluation
- Synthetic dataset generation

## Status

**Not yet implemented.** This module is reserved for future sprints.

## Architecture Notes

The ML model outputs validated risk signals that feed into the Policy Engine.
The model must NEVER directly authorize or execute payments.
All payment decisions go through deterministic policy enforcement.
