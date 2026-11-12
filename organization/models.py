from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=180, unique=True)
    slug = models.SlugField(max_length=200, unique=True)
    is_single_company = models.BooleanField(default=True, editable=False, unique=True)
    is_active = models.BooleanField(default=True)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(is_single_company=True),
                name="organization_is_single_company",
            ),
        ]

    def __str__(self):
        return self.name


class Region(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="regions")
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_region_per_org")]

    def __str__(self):
        return self.name


class Branch(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="branches")
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True, related_name="branches")
    name = models.CharField(max_length=120)
    city = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_branch_per_org")]

    def __str__(self):
        return self.name


class Department(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_department_per_org")]

    def __str__(self):
        return self.name


class Team(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="teams")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="teams")
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_team_per_org")]

    def __str__(self):
        return self.name


class JobRole(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="job_roles")
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_job_role_per_org")]

    def __str__(self):
        return self.name
