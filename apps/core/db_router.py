"""
Router de banco: apps gerenciados pelo Django ficam no `default`.
Modelos unmanaged dos modulos de negocio (Datafy/Taskfy/Schedule) podem
ler do banco `business` se marcarem `_database = 'business'` ou se o app
estiver listado abaixo.
"""

BUSINESS_APPS = set()  # preencha se quiser apontar um app inteiro para o banco business


class BusinessRouter:
    def _db_for(self, model):
        if model._meta.app_label in BUSINESS_APPS:
            return "business"
        if getattr(model, "_database", None):
            return model._database
        return None

    def db_for_read(self, model, **hints):
        return self._db_for(model)

    def db_for_write(self, model, **hints):
        return self._db_for(model)

    def allow_relation(self, obj1, obj2, **hints):
        db1 = self._db_for(type(obj1)) or "default"
        db2 = self._db_for(type(obj2)) or "default"
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in BUSINESS_APPS:
            return db == "business"
        return db == "default"
