FROM curlimages/curl:8.11.1

USER root
WORKDIR /bootstrap

COPY bootstrap-model.sh sabia-7b.Modelfile ./
RUN chmod +x /bootstrap/bootstrap-model.sh

ENTRYPOINT ["/bootstrap/bootstrap-model.sh"]
