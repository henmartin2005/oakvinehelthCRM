from .models import BookingRequest


def booking_counts(request):
    if not request.user.is_authenticated:
        return {
            'pending_bookings_count': 0,
            'current_user_role': '',
            'current_user_is_crm_admin': False,
            'current_user_is_assistant': False,
        }

    is_admin = request.user.is_superuser or request.user.groups.filter(name='Admin').exists()
    is_assistant = request.user.groups.filter(name='Assistant').exists()
    if is_admin:
        role = 'Admin'
    elif is_assistant:
        role = 'Assistant'
    elif request.user.groups.filter(name='User').exists():
        role = 'User'
    else:
        role = 'User'

    return {
        'pending_bookings_count': BookingRequest.objects.filter(status='pending').count(),
        'current_user_role': role,
        'current_user_is_crm_admin': is_admin,
        'current_user_is_assistant': is_assistant,
    }
