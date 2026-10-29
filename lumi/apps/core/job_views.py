"""``GET /api/v1/jobs/{id}``. See docs/CONTRATOS.md section 3.2."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import jobs
from apps.core.errors import ApiError


class JobView(APIView):
    def get(self, request, job_id):
        job = jobs.get_job(job_id, request.user.pk)
        if job is None:
            raise ApiError(
                "not_found",
                "Tarea no encontrada.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return Response(jobs.job_body(job))
