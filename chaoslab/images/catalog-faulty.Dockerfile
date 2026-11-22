# A deliberately defective, separately built demo revision. Never the default.
FROM aegisshop/catalog-service:0.1.0
COPY chaoslab/images/faulty_catalog.py /app/catalog_service/faulty_release.py
CMD ["python", "-m", "uvicorn", "catalog_service.faulty_release:app", "--host", "0.0.0.0", "--port", "9001"]
