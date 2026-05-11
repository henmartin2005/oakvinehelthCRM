from .models import BookingRequest


def booking_counts(request):
    if not request.user.is_authenticated:
        return {'pending_bookings_count': 0}

    return {
        'pending_bookings_count': BookingRequest.objects.filter(status='pending').count(),
    }
