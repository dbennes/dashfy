from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_alter_user_email")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("admin", "Administrador"),
                    ("planning", "Planejamento"),
                    ("supply", "Suprimentos"),
                    ("analyst", "Analista"),
                    ("viewer", "Visualizador"),
                    ("client", "Cliente"),
                ],
                default="viewer",
                max_length=20,
                verbose_name="Perfil",
            ),
        ),
    ]
