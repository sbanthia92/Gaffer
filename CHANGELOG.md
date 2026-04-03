# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Project skeleton with full CI/CD infrastructure
- FastAPI app with `/health` endpoint
- Multi-stage Dockerfiles for API and pipeline services
- Docker Compose for local development
- Kubernetes manifests (deployment, service, ingress, configmap)
- Terraform scaffold for ECR and EKS
- GitHub Actions CI (lint, test, docker build)
- GitHub Actions CD (build → ECR → rolling EKS deploy on merge to main)
