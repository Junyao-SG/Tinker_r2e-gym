REGION       ?= us-east-1
ACCOUNT_ID   ?= $(shell aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY ?= $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com
ECR_REPO     ?= tinker-r2egym
TAG          ?= latest
R2EGYM_REF   ?= main
RELEASE      ?= tinker-r2egym
NAMESPACE    ?= default
S3_BUCKET    ?= tinker-r2egym-$(shell date +%Y%m%d)
S3_PREFIX    ?= r2egym-trajectories

.PHONY: build push deploy deploy-training upgrade uninstall logs exec results lint template create-bucket create-ecr

## Create ECR repository
create-ecr:
	aws ecr create-repository --repository-name $(ECR_REPO) --region $(REGION) 2>/dev/null || echo "$(ECR_REPO) already exists"

## Build Docker image
build:
	docker build --platform linux/amd64 -f docker/Dockerfile.orchestrator \
		--build-arg R2EGYM_REF=$(R2EGYM_REF) \
		-t $(ECR_REGISTRY)/$(ECR_REPO):$(TAG) .

## Push image to ECR
push:
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(ECR_REGISTRY)
	docker push $(ECR_REGISTRY)/$(ECR_REPO):$(TAG)

## Deploy with Helm (inference mode)
deploy:
	helm install $(RELEASE) helm/tinker-r2egym \
		--namespace $(NAMESPACE) \
		--set image.repository=$(ECR_REGISTRY)/$(ECR_REPO) \
		--set image.tag=$(TAG) \
		--set aws.s3.bucket=$(S3_BUCKET) \
		--set aws.s3.prefix=$(S3_PREFIX)

## Deploy with Helm (training mode)
deploy-training:
	helm install $(RELEASE) helm/tinker-r2egym \
		--namespace $(NAMESPACE) \
		-f helm/tinker-r2egym/values-training.yaml \
		--set image.repository=$(ECR_REGISTRY)/$(ECR_REPO) \
		--set image.tag=$(TAG) \
		--set aws.s3.bucket=$(S3_BUCKET) \
		--set aws.s3.prefix=$(S3_PREFIX)

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

## Create S3 bucket for results
create-bucket:
	@test -n "$(S3_BUCKET)" || (echo "Usage: make create-bucket S3_BUCKET=my-bucket" && exit 1)
	aws s3api create-bucket --bucket $(S3_BUCKET) --region $(REGION) \
		$(if $(filter-out us-east-1,$(REGION)),--create-bucket-configuration LocationConstraint=$(REGION))
	@echo "Bucket created: s3://$(S3_BUCKET)"
	@echo "Set S3_BUCKET=$(S3_BUCKET) in your environment or pass it to make targets"

## Download results from S3
results:
	@test -n "$(S3_BUCKET)" || (echo "Set S3_BUCKET env var" && exit 1)
	mkdir -p ./results
	aws s3 sync "s3://$(S3_BUCKET)/$(S3_PREFIX)/" ./results/

## Lint Helm chart
lint:
	helm lint helm/tinker-r2egym
	helm lint helm/tinker-r2egym -f helm/tinker-r2egym/values-training.yaml

## Render Helm templates (dry-run)
template:
	helm template $(RELEASE) helm/tinker-r2egym \
		--set image.repository=test.ecr.io/tinker-r2egym \
		--set image.tag=test
