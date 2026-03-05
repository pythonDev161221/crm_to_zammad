from django.urls import path
from . import views

urlpatterns = [
    path('me/', views.MeView.as_view(), name='me'),

    # Tasks
    path('tasks/', views.TaskListCreateView.as_view(), name='task-list'),
    path('tasks/<int:pk>/', views.TaskDetailView.as_view(), name='task-detail'),
    path('tasks/<int:pk>/resolve/', views.TaskResolveView.as_view(), name='task-resolve'),

    # Tickets (under a task)
    path('tasks/<int:task_pk>/tickets/', views.TicketCreateView.as_view(), name='ticket-create'),
    path('tickets/<int:pk>/', views.TicketUpdateView.as_view(), name='ticket-update'),

    # Comments
    path('tasks/<int:task_pk>/comments/', views.CommentCreateView.as_view(), name='comment-create'),

    # IT Workers list (for delegation)
    path('it-workers/', views.ITWorkerListView.as_view(), name='it-workers'),
]
