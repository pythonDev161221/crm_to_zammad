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
    path('station/invite/', views.StationInviteView.as_view(), name='station-invite'),
    path('station/workers/', views.StationWorkersView.as_view(), name='station-workers'),
    path('station/workers/<int:pk>/', views.StationWorkerDeleteView.as_view(), name='station-worker-delete'),
    path('station/deputies/', views.StationDeputiesView.as_view(), name='station-deputies'),
    path('station/deputies/<int:pk>/', views.StationDeputyDeleteView.as_view(), name='station-deputy-delete'),

    # Station manager: their own stations
    path('my-stations/', views.MyStationsView.as_view(), name='my-stations'),

    # IT Manager: their own companies
    path('my-companies/', views.MyCompaniesView.as_view(), name='my-companies'),

    # IT Manager: manage company staff
    path('manage/it-workers/', views.ManageITWorkersView.as_view(), name='manage-it-workers'),
    path('manage/it-workers/<int:pk>/', views.ManageITWorkerDeleteView.as_view(), name='manage-it-worker-delete'),
    path('manage/supply-workers/', views.ManageSupplyWorkersView.as_view(), name='manage-supply-workers'),
    path('manage/supply-workers/<int:pk>/', views.ManageSupplyWorkerDeleteView.as_view(), name='manage-supply-worker-delete'),
    path('manage/station-managers/', views.ManageStationManagersView.as_view(), name='manage-station-managers'),
    path('manage/station-managers/<int:pk>/', views.ManageStationManagerDeleteView.as_view(), name='manage-station-manager-delete'),
    path('manage/stations/', views.ManageCompanyStationsView.as_view(), name='manage-stations'),
    path('manage/it-deputies/', views.ManageITDeputiesView.as_view(), name='manage-it-deputies'),
    path('manage/it-deputies/<int:pk>/', views.ManageITDeputyDemoteView.as_view(), name='manage-it-deputy-demote'),

    # Change password
    path('auth/change-password/', views.ChangePasswordView.as_view(), name='change-password'),
]
