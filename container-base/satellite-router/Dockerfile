FROM build-base

# install stress-ng for stress testing
RUN apt-get update && \
    apt-get install -y --no-install-recommends stress-ng && \
    rm -rf /var/lib/apt/lists/*

COPY materials/daemons /etc/frr/daemons
COPY scripts/entrypoint /Workspace/entrypoint
RUN chmod +x /Workspace/entrypoint
CMD [ "/Workspace/entrypoint"]
