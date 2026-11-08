"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
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
from django.urls import include, path

from core.views import SessionAPIView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/session/', SessionAPIView.as_view(), name='api-session'),
    path('api/etablissements/', include('etablissements.urls')),
    path('api/patients/', include('patients.urls')),
    path('api/soins/', include('soins.urls')),
    path('api/laboratoire/', include('laboratoire.urls')),
    path('api/facturation/', include('facturation.urls')),
    path('api/portail/', include('portail_patient.urls')),
    path('api/partenariats/', include('partenariats.urls')),
    path('api/equipements/', include('equipements.urls')),
    path('api/statistiques/', include('statistiques.urls')),
    path('', include('pharmacie.urls')),
]
