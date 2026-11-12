from .services import has_permission


class RBACBackend:
    def authenticate(self, request, **credentials):
        return None

    def get_user(self, user_id):
        return None

    def has_perm(self, user_obj, perm, obj=None):
        if obj is not None or "." not in perm:
            return False
        app_label, code = perm.split(".", 1)
        if app_label != "governance":
            return False
        return has_permission(user_obj, code.upper())
