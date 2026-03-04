from django.contrib import admin
from .models import Restaurante, Categoria, Adicional, Produto, Mesa, Entregador, Bairro, Pedido, ItemPedido

# ==========================================
# 1. ADMIN DA LOJA (O INQUILINO DO SAAS)
# ==========================================
@admin.register(Restaurante)
class RestauranteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'slug', 'dono', 'aberta', 'status_assinatura', 'vencimento_assinatura')
    list_filter = ('status_assinatura', 'aberta', 'criado_em')
    search_fields = ('nome', 'slug', 'dono__username', 'telefone', 'endereco')
    prepopulated_fields = {'slug': ('nome',)} 
    list_editable = ('aberta', 'status_assinatura', 'vencimento_assinatura') 
    list_per_page = 20 
    
    # 🚀 O SEGREDO PRO: Sem campos duplicados agora!
    fieldsets = (
        ('Identificação', {
            'fields': ('dono', 'nome', 'slug', 'logo', 'cor_principal')
        }),
        ('Contato e Endereço', {
            'fields': ('telefone', 'endereco', 'cep', 'lat_padrao', 'lng_padrao')
        }),
        ('Operação e Horários', {
            'fields': (
                'aberta', 'tempo_entrega', 'horario_abertura', 'horario_fechamento', 'mensagem_fechado',
                'abre_segunda', 'abre_terca', 'abre_quarta', 'abre_quinta', 'abre_sexta', 'abre_sabado', 'abre_domingo'
            )
        }),
        ('Cobrança SaaS (AlianceFood)', {
            'fields': ('status_assinatura', 'vencimento_assinatura', 'valor_mensalidade'),
            'classes': ('collapse',) 
        }),
        ('Integrações (API)', {
            'fields': ('mp_access_token', 'ultramsg_instance', 'ultramsg_token'),
            'classes': ('collapse',)
        }),
    )

# ==========================================
# 2. CARDÁPIO E PRODUTOS 
# ==========================================
@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'restaurante') 
    list_filter = ('restaurante',) 
    search_fields = ('nome', 'restaurante__nome')
    autocomplete_fields = ['restaurante'] # 🚀 Transforma o menu de restaurantes numa barra de pesquisa!

@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'categoria', 'preco', 'restaurante', 'ativo')
    list_filter = ('restaurante', 'categoria', 'ativo') # Super filtros cruzados
    search_fields = ('nome', 'categoria__nome', 'restaurante__nome')
    list_editable = ('preco', 'ativo')
    autocomplete_fields = ['restaurante', 'categoria'] 
    list_per_page = 30

@admin.register(Adicional)
class AdicionalAdmin(admin.ModelAdmin):
    list_display = ('nome', 'preco', 'restaurante') 
    list_filter = ('restaurante',)
    search_fields = ('nome', 'restaurante__nome')
    autocomplete_fields = ['restaurante']

# ==========================================
# 3. PEDIDOS E CAIXA
# ==========================================
class ItemPedidoInline(admin.TabularInline):
    model = ItemPedido
    extra = 0 
    readonly_fields = ('produto', 'quantidade', 'preco_unitario', 'observacao')
    autocomplete_fields = ['produto']

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    # Visão de Raio-X total do pedido
    list_display = ('id', 'cliente_nome', 'origem', 'status', 'total', 'forma_pagamento', 'restaurante', 'criado_em')
    
    # 🚀 Super Filtros Laterais
    list_filter = ('restaurante', 'status', 'origem', 'forma_pagamento', 'tipo_entrega', 'criado_em') 
    
    search_fields = ('cliente_nome', 'cliente_whatsapp', 'id_pedido', 'restaurante__nome')
    inlines = [ItemPedidoInline] 
    date_hierarchy = 'criado_em' 
    autocomplete_fields = ['restaurante', 'mesa', 'entregador']
    list_per_page = 25

@admin.register(ItemPedido)
class ItemPedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'pedido', 'produto', 'quantidade', 'preco_unitario')
    list_filter = ('pedido__restaurante', 'produto__categoria')
    search_fields = ('pedido__id', 'produto__nome', 'pedido__cliente_nome')

# ==========================================
# 4. LOGÍSTICA E OPERAÇÃO
# ==========================================
@admin.register(Mesa)
class MesaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'restaurante', 'ocupada')
    list_filter = ('restaurante', 'ocupada')
    search_fields = ('numero', 'restaurante__nome')
    ordering = ('restaurante', 'numero')
    autocomplete_fields = ['restaurante']

@admin.register(Entregador)
class EntregadorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'restaurante') 
    list_filter = ('restaurante',)
    search_fields = ('nome', 'restaurante__nome')
    autocomplete_fields = ['restaurante']

@admin.register(Bairro)
class BairroAdmin(admin.ModelAdmin):
    list_display = ('nome', 'taxa', 'restaurante') 
    list_filter = ('restaurante',)
    search_fields = ('nome', 'restaurante__nome')
    list_editable = ('taxa',)
    autocomplete_fields = ['restaurante']