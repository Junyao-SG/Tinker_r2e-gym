REGION       ?= us-east-1
ACCOUNT_ID   ?= $(shell aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY ?= $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com
ECR_REPO     ?= r2e-eks
TAG          ?= latest
R2EGYM_REF   ?= main
RELEASE      ?= r2e-eks
NAMESPACE    ?= default
S3_BUCKET    ?= r2e-eks-$(shell date +%Y%m%d)
S3_PREFIX    ?= r2egym-trajectories

CLUSTER      ?= r2e-eks

# MODE: eval (default, vLLM) | training | tinker
MODE         ?= eval

.PHONY: create-cluster create-secrets build push deploy upgrade uninstall logs exec results lint template create-bucket create-ecr install-autoscaler install-nvidia-plugin add-gpu-nodes teardown

## Create EKS cluster
create-cluster:
	eksctl create cluster -f cluster/cluster.yaml

## Create K8s secrets from .env file
create-secrets:
	kubectl create secret generic tinker-credentials --from-env-file=.env

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

## Deploy with Helm (use MODE=eval|training|tinker)
deploy:
	helm install $(RELEASE) helm/r2e-eks \
		--namespace $(NAMESPACE) \
		$(if $(filter training,$(MODE)),-f helm/r2e-eks/values-training.yaml) \
		$(if $(filter tinker,$(MODE)),-f helm/r2e-eks/values-tinker.yaml) \
		--set image.repository=$(ECR_REGISTRY)/$(ECR_REPO) \
		--set image.tag=$(TAG) \
		--set aws.s3.bucket=$(S3_BUCKET) \
		--set aws.s3.prefix=$(S3_PREFIX)

## Upgrade existing release
upgrade:
	helm upgrade $(RELEASE) helm/r2e-eks \
		--namespace $(NAMESPACE) \
		$(if $(filter training,$(MODE)),-f helm/r2e-eks/values-training.yaml) \
		$(if $(filter tinker,$(MODE)),-f helm/r2e-eks/values-tinker.yaml) \
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

## Install cluster autoscaler (requires IRSA service account from cluster.yaml)
install-autoscaler:
	helm repo add autoscaler https://kubernetes.github.io/autoscaler 2>/dev/null || true
	helm repo update autoscaler
	helm install cluster-autoscaler autoscaler/cluster-autoscaler \
		--namespace kube-system \
		--set autoDiscovery.clusterName=$(CLUSTER) \
		--set awsRegion=$(REGION) \
		--set rbac.serviceAccount.create=false \
		--set rbac.serviceAccount.name=cluster-autoscaler \
		--set extraArgs.balance-similar-node-groups=true \
		--set extraArgs.skip-nodes-with-system-pods=false \
		--set extraArgs.scale-down-unneeded-time=5m

## Teardown: uninstall Helm release and delete EKS cluster
teardown:
	helm uninstall $(RELEASE) --namespace $(NAMESPACE)
	helm uninstall cluster-autoscaler --namespace kube-system
	eksctl delete cluster --name $(CLUSTER) --region $(REGION)

## Add GPU node group (run separately if cluster already exists)
add-gpu-nodes:
	eksctl create nodegroup --config-file=cluster/cluster.yaml --include=gpu-inference

## Install NVIDIA device plugin via Helm (fallback if EKS addon unavailable)
install-nvidia-plugin:
	helm repo add nvdp https://nvidia.github.io/k8s-device-plugin 2>/dev/null || true
	helm repo update nvdp
	helm install nvidia-device-plugin nvdp/nvidia-device-plugin \
		--namespace kube-system \
		--set tolerations[0].key=nvidia.com/gpu \
		--set tolerations[0].operator=Exists \
		--set tolerations[0].effect=NoSchedule

## Lint Helm chart
lint:
	helm lint helm/r2e-eks
	helm lint helm/r2e-eks -f helm/r2e-eks/values-training.yaml
	helm lint helm/r2e-eks -f helm/r2e-eks/values-tinker.yaml

## Render Helm templates (dry-run, use MODE=eval|training|tinker)
template:
	helm template $(RELEASE) helm/r2e-eks \
		$(if $(filter training,$(MODE)),-f helm/r2e-eks/values-training.yaml) \
		$(if $(filter tinker,$(MODE)),-f helm/r2e-eks/values-tinker.yaml) \
		--set image.repository=test.ecr.io/r2e-eks \
		--set image.tag=test
