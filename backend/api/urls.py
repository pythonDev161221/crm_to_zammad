from django.urls import path
from . import views

urlpatterns = [
    path('me/', views.MeView.as_view(), name='me'),

    # Tickets (main entity, created by worker)
    path('tickets/', views.TicketListCreateView.as_view(), name='ticket-list'),
    path('tickets/<int:pk>/', views.TicketDetailView.as_view(), name='ticket-detail'),
    path('tickets/<int:pk>/resolve/', views.TicketResolveView.as_view(), name='ticket-resolve'),

    # Tasks (assigned to IT workers within a ticket)
    path('tickets/<int:ticket_pk>/tasks/', views.TaskCreateView.as_view(), name='task-create'),
    path('tasks/<int:pk>/', views.TaskUpdateView.as_view(), name='task-update'),

    # Comments
    path('tickets/<int:ticket_pk>/comments/', views.CommentCreateView.as_view(), name='comment-create'),

    # IT Workers list (for delegation)
    path('it-workers/', views.ITWorkerListView.as_view(), name='it-workers'),

    # Station management
    path('station/workers/', views.StationWorkersView.as_view(), name='station-workers'),
    path('station/workers/<int:pk>/', views.StationWorkerDeleteView.as_view(), name='station-worker-delete'),

    # Change password
    path('auth/change-password/', views.ChangePasswordView.as_view(), name='change-password'),
]
