REGION       ?= us-east-1
ACCOUNT_ID   ?= $(shell aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY ?= $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com
ECR_REPO     ?= tinker-r2egym
TAG          ?= latest
R2EGYM_REF   ?= main
RELEASE      ?= tinker-r2egym
NAMESPACE    ?= default

.PHONY: build push deploy upgrade uninstall logs exec results lint template

## Build Docker images
build:
	docker build -f docker/Dockerfile.orchestrator \
		--build-arg R2EGYM_REF=$(R2EGYM_REF) \
		-t $(ECR_REGISTRY)/$(ECR_REPO):$(TAG) .
	docker build -f docker/Dockerfile.proxy \
		-t $(ECR_REGISTRY)/$(ECR_REPO)-proxy:$(TAG) .

## Push images to ECR
push:
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)
	docker push $(ECR_REGISTRY)/$(ECR_REPO):$(TAG)
	docker push $(ECR_REGISTRY)/$(ECR_REPO)-proxy:$(TAG)

## Deploy with Helm (inference mode)
deploy:
	helm install $(RELEASE) helm/tinker-r2egym \
		--namespace $(NAMESPACE) \
		--set image.repository=$(ECR_REGISTRY)/$(ECR_REPO) \
		--set image.tag=$(TAG)

## Deploy with Helm (training mode)
deploy-training:
	helm install $(RELEASE) helm/tinker-r2egym \
		--namespace $(NAMESPACE) \
		-f helm/tinker-r2egym/values-training.yaml \
		--set image.repository=$(ECR_REGISTRY)/$(ECR_REPO) \
		--set image.tag=$(TAG) \
		--set proxy.image.repository=$(ECR_REGISTRY)/$(ECR_REPO)-proxy \
		--set proxy.image.tag=$(TAG)

## Upgrade existing release
upgrade:
	helm upgrade $(RELEASE) helm/tinker-r2egym \
		--namespace $(NAMESPACE) \
		--set image.repository=$(ECR_REGISTRY)/$(ECR_REPO) \
		--set image.tag=$(TAG)

## Uninstall
uninstall:
	helm uninstall $(RELEASE) --namespace $(NAMESPACE)

## Show orchestrator logs
logs:
	kubectl logs -n $(NAMESPACE) -l app=$(RELEASE)-orchestrator -f

## Exec into orchestrator pod
exec:
	kubectl exec -n $(NAMESPACE) -it \
		$$(kubectl get pod -n $(NAMESPACE) -l app=$(RELEASE)-orchestrator -o jsonpath='{.items[0].metadata.name}') \
		-- /bin/bash

## Download results from S3
results:
	./scripts/download-results.sh

## Lint Helm chart
lint:
	helm lint helm/tinker-r2egym
	helm lint helm/tinker-r2egym -f helm/tinker-r2egym/values-inference.yaml
	helm lint helm/tinker-r2egym -f helm/tinker-r2egym/values-training.yaml

## Render Helm templates (dry-run)
template:
	helm template $(RELEASE) helm/tinker-r2egym \
		--set image.repository=test.ecr.io/tinker-r2egym \
		--set image.tag=test
