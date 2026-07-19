#!/bin/bash

# Use the correct AWS profile
export AWS_PROFILE=octopus-sandbox

# Exit on error
set -e

# Configuration
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="232672477021"
ECR_REPOSITORY="api-sandbox-us-east-1"
IMAGE_TAG="latest"
DOCKER_IMAGE_NAME="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting ECR build and push process...${NC}"

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed. Please install it first.${NC}"
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

# Login to ECR
echo -e "${GREEN}Logging into ECR...${NC}"
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Check if repository exists, create if it doesn't
echo -e "${GREEN}Checking if ECR repository exists...${NC}"
if ! aws ecr describe-repositories --repository-names ${ECR_REPOSITORY} --region ${AWS_REGION} &> /dev/null; then
    echo -e "${YELLOW}Repository ${ECR_REPOSITORY} does not exist. Creating it...${NC}"
    aws ecr create-repository --repository-name ${ECR_REPOSITORY} --region ${AWS_REGION}
fi

# Build Docker image
echo -e "${GREEN}Building Docker image...${NC}"
docker build -t ${DOCKER_IMAGE_NAME}:${IMAGE_TAG} .

# Tag the image
echo -e "${GREEN}Tagging Docker image...${NC}"
docker tag ${DOCKER_IMAGE_NAME}:${IMAGE_TAG} ${DOCKER_IMAGE_NAME}:${IMAGE_TAG}

# Push the image to ECR
echo -e "${GREEN}Pushing Docker image to ECR...${NC}"
docker push ${DOCKER_IMAGE_NAME}:${IMAGE_TAG}

echo -e "${GREEN}✅ Successfully built and pushed image to ECR!${NC}"
echo -e "${GREEN}Image: ${DOCKER_IMAGE_NAME}:${IMAGE_TAG}${NC}"

# Optional: Show the image URI for use in Kubernetes
echo -e "${YELLOW}Image URI for Kubernetes:${NC}"
echo "${DOCKER_IMAGE_NAME}:${IMAGE_TAG}" 