"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from patients import views

urlpatterns = [
    path('api/booking-config/', views.api_booking_config, name='api_booking_config'),
    path('api/book-appointment/', views.api_book_appointment, name='api_book_appointment'),
    path('api/available-slots/', views.api_available_slots, name='api_available_slots'),
    path('api/appointment-day-schedule/', views.api_appointment_day_schedule, name='api_appointment_day_schedule'),
    path('api/n8n/appointments/', views.n8n_pending_appointments, name='n8n_appointments'),
    path('', views.dashboard_view, name='dashboard'),
    path('profile/', views.admin_profile_view, name='admin_profile'),
    path('users/<int:pk>/edit/', views.user_update_view, name='user_update'),
    path('users/<int:pk>/delete/', views.user_delete_view, name='user_delete'),
    path('patients/', views.patient_list_view, name='patient_list'),
    path('patients/new/', views.patient_create_view, name='patient_create'),
    path('patients/<int:pk>/edit/', views.patient_update_view, name='patient_update'),
    path('appointments/', views.appointment_calendar_view, name='appointments_calendar'),
    path('appointments/list/', views.appointment_list_view, name='appointment_list'),
    path('appointments/new/', views.appointment_create_view, name='appointment_create'),
    path('appointments/<int:pk>/edit/', views.appointment_update_view, name='appointment_update'),
    path('appointments/<int:pk>/edit/', views.appointment_update_view, name='appointment_edit'),
    path('appointments/<int:pk>/notify/', views.appointment_notify_view, name='appointment_notify'),
    path('payments/', views.payment_list_view, name='payment_list'),
    path('payments/new/', views.payment_create_view, name='payment_create'),
    path('payments/<int:pk>/edit/', views.payment_update_view, name='payment_update'),
    path('bookings/', views.booking_requests_view, name='booking_requests'),
    path('bookings/<int:pk>/review/', views.booking_confirm_view, name='booking_confirm'),
    path('bookings/settings/', views.booking_config_view, name='booking_config'),
    path('login/', auth_views.LoginView.as_view(template_name='patients/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
]
