FROM ghcr.io/actions/actions-runner:latest
USER root
RUN KUBECTL_VERSION=v1.35.0 && \
    curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/kubectl
USER runner
