# Generated for local Oak & Vine CRM patient history.

import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0004_bookinglog'),
    ]

    operations = [
        migrations.CreateModel(
            name='PatientActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('activity_type', models.CharField(choices=[('note', 'Note'), ('call', 'Call'), ('followup', 'Follow-up'), ('admin', 'Admin')], default='note', max_length=20)),
                ('title', models.CharField(max_length=160)),
                ('notes', models.TextField(blank=True)),
                ('user_id', models.CharField(blank=True, max_length=64)),
                ('user_name', models.CharField(blank=True, max_length=150)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='patients.patient')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['patient', '-created_at'], name='patients_pa_patient_14868f_idx')],
            },
        ),
    ]
