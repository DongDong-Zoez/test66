# 同步 to-pdf：下載 PDF 到本機
curl -X POST -o out.pdf http://localhost:8000/files/<file_id>/to-pdf
# 也會在 S3 生成：
# s3://<bucket>/alice/artifacts/<file_id>/<task_run_id>/to-pdf/<stem>.pdf
