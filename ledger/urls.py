from django.urls import path
from . import views
urlpatterns = [path('', views.dashboard, name='dashboard'),
    path('operations/', views.operations, name='operations'), path('deliveries/', views.deliveries, name='deliveries'),
    path('partners/', views.partners, name='partners'),
    path('operations/new/', views.record_form, {'kind':'operations'}, name='operation_new'),
    path('deliveries/new/', views.record_form, {'kind':'deliveries'}, name='delivery_new'),
    path('records/<str:kind>/<int:pk>/', views.record_detail, name='record_detail'),
    path('records/<str:kind>/<int:pk>/edit/', views.record_form, name='record_edit'),
    path('records/<str:kind>/<int:pk>/delete/', views.record_delete, name='record_delete'),
    path('imports/', views.imports, name='imports'), path('imports/<int:pk>/', views.import_detail, name='import_detail'),
    path('imports/<int:pk>/confirm/', views.import_confirm, name='import_confirm'),
    path('imports/<int:pk>/source/', views.source_download, name='source_download'),
    path('sheets/', views.sheets, name='sheets'), path('sheets/<int:pk>/', views.sheet_detail, name='sheet_detail'),
    path('exports/', views.exports, name='exports'), path('exports/<str:kind>/', views.export_download, name='export_download'),
    path('help/', views.help_page, name='help')]
