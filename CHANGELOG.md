# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-19

### Security

- The Store API now requires a bearer token on every route except the storefront routes (`GET /api/health`, `GET /api/products`, `GET /api/products/{id}`, `POST /api/orders`, `POST /api/carts/save`). The token is generated in AWS Secrets Manager and read at runtime by each server-side caller. The admin dashboard asks for it at sign-in. See the Security section in the README.
- CORS on the Store API is limited to the CloudFront site domain.
- The OpenClaw gateway token moved from the CloudFormation template to AWS Secrets Manager.
- Anonymous orders can no longer overwrite an existing customer's name or email.

### Changed

- Amazon EKS 1.30 to 1.37 (1.30 is no longer supported for new clusters), with the matching kubectl layer and Amazon Linux 2023 nodes.
- Dispatcher Lambda runtime Node.js 20 to Node.js 24.

### Removed

- The unused API Gateway API key and usage plan, and the `StoreApiKeyId` stack output.

### Upgrade notes

- Existing deployments: Amazon EKS upgrades one minor version at a time, so updating an existing stack in place fails. Run `npx cdk destroy`, then `npx cdk deploy`. This deletes the RDS database and everything in it; the new deploy re-seeds the demo catalog. To keep your data, take an RDS snapshot before you destroy the stack and restore from it afterwards.

## [1.0.0] - 2026-06-18

### Added

- Initial commit.
