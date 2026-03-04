from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

# Importando todas as views
from core.views import (
    index, api_finalizar, painel_cozinha, 
    api_alterar_status, dashboard, imprimir_cupom,
    rastreio_pedido, painel_motoboy, caixa_balcao, htmx_dashboard_kpis, htmx_dashboard_novos,
    htmx_dashboard_cozinha, htmx_dashboard_logistica, api_salvar_gps,
    gerenciar_cardapio, editar_produto, api_toggle_produto, gerenciar_mesas, gerar_qrcode,
    api_detalhes_mesa, api_fechar_mesa, webhook_mercadopago, painel_caixa,
    api_assumir_entrega, api_listar_mesas_aguardando, api_gerar_pix_operador, api_receber_mesa,
    api_status_pix_mesa, api_listar_bairros, api_verificar_alertas, login_motoboy, logout_motoboy,
    api_finalizar_entrega, api_aceitar_corrida, api_localizacao_motoboy, landing_page, configuracoes_loja, minha_assinatura, api_gerar_pagamento_saas, manifest_pwa
)

urlpatterns = [
    # 1. Rota do Admin (Acesso Técnico)
    path('admin/', admin.site.urls),
    
    # 2. LOGIN PERSONALIZADO 
    path('accounts/login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    
    # 3. Resto da Autenticação (Logout, etc)
    path('accounts/', include('django.contrib.auth.urls')),
    
    # ==========================================
    # 🏢 ROTAS PÚBLICAS (SaaS - Exigem o SLUG da Loja)
    # ==========================================
    path('', landing_page, name='landing_page'),
    path('loja/<slug:slug>/', index, name='index'),
    path('loja/<slug:slug>/manifest.json', manifest_pwa, name='manifest_pwa'),
    path('loja/<slug:slug>/rastreio/<uuid:pedido_id>/', rastreio_pedido, name='rastreio'),
    path('api/bairros/<slug:slug>/', api_listar_bairros, name='api_listar_bairros'),
    
    # ==========================================
    # ⚙️ APIs GERAIS (Funcionam via POST ou Webhook)
    # ==========================================
    path('api/finalizar/', api_finalizar, name='api_finalizar'),
    path('api/webhook/mercadopago/', webhook_mercadopago, name='webhook_mercadopago'),
    
    # ==========================================
    # 👨‍🍳 PAINÉIS DE ADMINISTRAÇÃO E COZINHA (Protegidos por Login)
    # ==========================================
    path('dashboard/', dashboard, name='dashboard'),
    path('cozinha/', painel_cozinha, name='painel_cozinha'),
    path('caixa/', caixa_balcao, name='caixa_balcao'),
    path('gestao-caixa/', painel_caixa, name='painel_caixa'),
    path('cardapio-admin/', gerenciar_cardapio, name='gerenciar_cardapio'),
    path('cardapio-admin/editar/<int:produto_id>/', editar_produto, name='editar_produto'),
    path('mesas/', gerenciar_mesas, name='gerenciar_mesas'),
    path('painel/configuracoes/', configuracoes_loja, name='configuracoes_loja'),
    path('painel/assinatura/', minha_assinatura, name='minha_assinatura'),
   path('api/gerar_pagamento_saas/', api_gerar_pagamento_saas, name='api_gerar_pagamento_saas'),
    # HTMX (Dashboard ao Vivo)
    path('htmx/kpis/', htmx_dashboard_kpis, name='htmx_kpis'),
    path('htmx/novos/', htmx_dashboard_novos, name='htmx_novos'),
    path('htmx/cozinha/', htmx_dashboard_cozinha, name='htmx_cozinha'),
    path('htmx/logistica/', htmx_dashboard_logistica, name='htmx_logistica'),
    
    # ==========================================
    # 🛵 APLICATIVO DO MOTOBOY
    # ==========================================
    path('motoboy/login/', login_motoboy, name='login_motoboy'),
    path('motoboy/sair/', logout_motoboy, name='logout_motoboy'),
    path('motoboy/', painel_motoboy, name='painel_motoboy'),
    
    # ==========================================
    # 🔌 APIs INTERNAS (Ações de Botões no Painel)
    # ==========================================
    path('imprimir/<int:pedido_id>/', imprimir_cupom, name='imprimir_cupom'),
    path('api/status/<int:pedido_id>/', api_alterar_status, name='api_alterar_status'),
    path('api/assumir/<int:pedido_id>/', api_assumir_entrega, name='api_assumir_entrega'),
    path('api/gps/<int:pedido_id>/', api_salvar_gps, name='api_salvar_gps'),
    path('api/finalizar_entrega/<int:pedido_id>/', api_finalizar_entrega, name='api_finalizar_entrega'),
    path('api/aceitar_corrida/<int:pedido_id>/', api_aceitar_corrida, name='api_aceitar_corrida'),
    path('api/localizacao_motoboy/<str:pedido_id>/', api_localizacao_motoboy, name='api_localizacao_motoboy'),
    path('api/verificar_alertas/', api_verificar_alertas, name='api_verificar_alertas'),
    path('api/toggle/<int:produto_id>/', api_toggle_produto, name='api_toggle_produto'),
    
    
    # APIs de Mesa
    path('mesas/qr/<int:mesa_id>/', gerar_qrcode, name='gerar_qrcode'),
    path('api/mesa/<int:mesa_id>/detalhes/', api_detalhes_mesa, name='api_detalhes_mesa'),
    path('api/fechar_mesa/<int:mesa_id>/', api_fechar_mesa, name='api_fechar_mesa'),
    path('api/mesas_aguardando/', api_listar_mesas_aguardando, name='api_mesas_aguardando'),
    path('api/gerar_pix_operador/<int:mesa_numero>/', api_gerar_pix_operador, name='api_gerar_pix_operador'),
    path('api/receber_mesa/<int:mesa_numero>/', api_receber_mesa, name='api_receber_mesa'),
    path('api/status_pix_mesa/<int:mesa_numero>/', api_status_pix_mesa, name='api_status_pix_mesa'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)