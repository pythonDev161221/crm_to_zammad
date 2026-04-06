from datetime import date, timedelta, timezone as dt_timezone

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Sum
from django.utils import timezone
from django.views import View
from django.shortcuts import render

from tasks.models import Task, Ticket


def _parse_date(value, fallback):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback


def _fmt_duration(td):
    if td is None:
        return '—'
    total = int(td.total_seconds())
    h, remainder = divmod(abs(total), 3600)
    m, s = divmod(remainder, 60)
    return f'{h}h {m:02d}m'


class StatsView(View):
    template_name = 'admin/stats.html'

    def get(self, request):
        today = timezone.now().date()
        default_from = today.replace(day=1)
        default_to = today

        date_from = _parse_date(request.GET.get('date_from'), default_from)
        date_to = _parse_date(request.GET.get('date_to'), default_to)

        # Inclusive end: filter up to end of date_to
        dt_from = timezone.datetime.combine(date_from, timezone.datetime.min.time()).replace(tzinfo=dt_timezone.utc)
        dt_to = timezone.datetime.combine(date_to + timedelta(days=1), timezone.datetime.min.time()).replace(tzinfo=dt_timezone.utc)

        worker_stats = list(
            Task.objects.filter(
                status=Task.Status.DONE,
                finished_at__gte=dt_from,
                finished_at__lt=dt_to,
                started_at__isnull=False,
            ).values(
                'assigned_to__id',
                'assigned_to__username',
                'assigned_to__first_name',
                'assigned_to__last_name',
            ).annotate(
                tasks_done=Count('id'),
                avg_duration=Avg(ExpressionWrapper(
                    F('finished_at') - F('started_at'),
                    output_field=DurationField(),
                )),
                total_duration=Sum(ExpressionWrapper(
                    F('finished_at') - F('started_at'),
                    output_field=DurationField(),
                )),
            ).order_by('-tasks_done')
        )

        for row in worker_stats:
            full = f"{row['assigned_to__first_name']} {row['assigned_to__last_name']}".strip()
            row['display_name'] = full or row['assigned_to__username']
            row['avg_duration_fmt'] = _fmt_duration(row['avg_duration'])
            row['total_duration_fmt'] = _fmt_duration(row['total_duration'])

        company_stats = list(
            Ticket.objects.filter(
                status=Ticket.Status.RESOLVED,
                resolved_at__gte=dt_from,
                resolved_at__lt=dt_to,
            ).values(
                'station__company__name',
            ).annotate(
                total=Count('id'),
                avg_resolution=Avg(ExpressionWrapper(
                    F('resolved_at') - F('created_at'),
                    output_field=DurationField(),
                )),
            ).order_by('station__company__name')
        )

        for row in company_stats:
            row['company'] = row['station__company__name'] or '(no company)'
            row['avg_resolution_fmt'] = _fmt_duration(row['avg_resolution'])

        context = {
            **self._admin_context(request),
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'worker_stats': worker_stats,
            'company_stats': company_stats,
        }
        return render(request, self.template_name, context)

    def _admin_context(self, request):
        from django.contrib.admin import site
        return {
            'site_header': site.site_header,
            'site_title': site.site_title,
            'title': 'SLI Stats',
            'has_permission': True,
        }
