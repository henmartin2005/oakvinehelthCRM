# Generated for local Oak & Vine CRM booking audit logs.

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0003_bookingconfig_alter_appointment_visit_type_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='BookingLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.TextField()),
                ('log_type', models.CharField(choices=[('system', 'System/auto'), ('warning', 'Alert/warning'), ('admin', 'Admin action')], default='system', max_length=20)),
                ('user_id', models.CharField(blank=True, max_length=64)),
                ('user_name', models.CharField(blank=True, max_length=150)),
                ('details', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='patients.bookingrequest')),
            ],
            options={
                'ordering': ['created_at'],
                'indexes': [models.Index(fields=['booking'], name='patients_bo_booking_235fa1_idx')],
            },
        ),
    ]
