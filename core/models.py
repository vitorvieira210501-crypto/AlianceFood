from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.utils import timezone
import uuid
import datetime
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile
import sys


def comprimir_imagem(imagem, tamanho_max=(800, 800)):
    """ Pega uma imagem pesada e converte para WEBP leve e rápido """
    if not imagem: return None
    
    img = Image.open(imagem)
    
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        fundo = Image.new('RGB', img.size, (255, 255, 255))
        fundo.paste(img, mask=img.split()[3])
        img = fundo
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    img.thumbnail(tamanho_max, Image.Resampling.LANCZOS)
    
    output = BytesIO()
    img.save(output, format='WEBP', quality=80)
    output.seek(0)
    
    nome_arquivo = f"{imagem.name.split('.')[0]}.webp"
    return InMemoryUploadedFile(output, 'ImageField', nome_arquivo, 'image/webp', sys.getsizeof(output), None)
# ==========================================
# 🏢 1. O CORAÇÃO DO SAAS (O INQUILINO)
# ==========================================
import datetime # Certifique-se de que isto está no topo do models.py se ainda não estiver
from django.db import models
from django.contrib.auth.models import User

class Restaurante(models.Model):
    dono = models.OneToOneField(User, on_delete=models.CASCADE, related_name='restaurante_saas')
    nome = models.CharField(max_length=100, verbose_name="Nome do Restaurante")
    slug = models.SlugField(unique=True, help_text="Nome na URL. Ex: salgadinho-lanches")
    
    # --- INFORMAÇÕES PÚBLICAS ---
    telefone = models.CharField(max_length=20, blank=True, null=True, verbose_name="WhatsApp")
    endereco = models.TextField(blank=True, null=True, verbose_name="Endereço Físico")
    cep = models.CharField(max_length=15, blank=True, null=True, verbose_name="CEP")
    
    # --- FUNCIONAMENTO E OPERAÇÃO ---
    aberta = models.BooleanField(default=True, verbose_name="Botão de Pânico (Forçar Abertura/Fechamento)") 
    tempo_entrega = models.CharField(max_length=50, default="30-45 min", blank=True, null=True, verbose_name="Previsão de Entrega")
    horario_abertura = models.TimeField(default=datetime.time(18, 0), verbose_name="Abre às")
    horario_fechamento = models.TimeField(default=datetime.time(0, 0), verbose_name="Fecha às")
    mensagem_fechado = models.CharField(max_length=200, default="Estamos fechados no momento. Voltamos às 18h!", verbose_name="Aviso de Loja Fechada")
    
    # 📅 --- CALENDÁRIO INTELIGENTE (DIAS DE FOLGA) ---
    abre_segunda = models.BooleanField("Abre Segunda", default=True)
    abre_terca = models.BooleanField("Abre Terça", default=True)
    abre_quarta = models.BooleanField("Abre Quarta", default=True)
    abre_quinta = models.BooleanField("Abre Quinta", default=True)
    abre_sexta = models.BooleanField("Abre Sexta", default=True)
    abre_sabado = models.BooleanField("Abre Sábado", default=True)
    abre_domingo = models.BooleanField("Abre Domingo", default=True)

    # --- PERSONALIZAÇÃO (CO-BRANDING SAAS) ---
    logo = models.ImageField(upload_to='logos_restaurantes/', null=True, blank=True, verbose_name="Logótipo da Loja")
    cor_principal = models.CharField(max_length=7, default="#FF6B00", verbose_name="Cor Principal (HEX)")

    # --- INTEGRAÇÕES SAAS ---
    mp_access_token = models.CharField(max_length=255, blank=True, null=True, verbose_name="Token Mercado Pago")
    ultramsg_instance = models.CharField(max_length=100, blank=True, null=True, verbose_name="ID Instância UltraMsg")
    ultramsg_token = models.CharField(max_length=100, blank=True, null=True, verbose_name="Token UltraMsg")
    
    # --- GPS ---
    lat_padrao = models.CharField(max_length=50, default='-22.7561', verbose_name="Latitude da Loja")
    lng_padrao = models.CharField(max_length=50, default='-43.4607', verbose_name="Longitude da Loja")

    criado_em = models.DateTimeField(auto_now_add=True)

    # 🚀 --- MÁQUINA DE COBRANÇA (SaaS) ---
    STATUS_ASSINATURA = (
        ('TRIAL', 'Período de Teste (Grátis)'),
        ('ATIVO', 'Assinatura Ativa'),
        ('VENCIDO', 'Pagamento Atrasado (Bloqueado)'),
    )
    status_assinatura = models.CharField(max_length=20, choices=STATUS_ASSINATURA, default='TRIAL', verbose_name="Status do Plano")
    vencimento_assinatura = models.DateField(null=True, blank=True, verbose_name="Vencimento da Mensalidade")
    valor_mensalidade = models.DecimalField(max_digits=10, decimal_places=2, default=149.90, verbose_name="Valor do Plano (R$)")

    class Meta:
        verbose_name = "Restaurante (Loja)"
        verbose_name_plural = "Restaurantes (Lojas)"

    def __str__(self):
        return self.nome

    @property
    def esta_aberta_agora(self):
        """ Lógica que respeita a madrugada, dias de folga e o botão de pânico """
        # 1. Se o dono desligou no botão, está fechada e ponto final.
        if not self.aberta: 
            return False
            
        # 2. Verifica se hoje é o dia de folga!
        hoje_weekday = timezone.localtime().weekday() # 0 = Seg, 6 = Dom
        dias_funcionamento = [
            self.abre_segunda, self.abre_terca, self.abre_quarta, 
            self.abre_quinta, self.abre_sexta, self.abre_sabado, self.abre_domingo
        ]
        if not dias_funcionamento[hoje_weekday]:
            return False # Se for falso, está fechado o dia todo!

        # 3. Se o botão está ligado e não é dia de folga, vamos ver se o relógio permite.
        hora_atual = timezone.localtime().time()
        if self.horario_abertura < self.horario_fechamento:
            return self.horario_abertura <= hora_atual <= self.horario_fechamento
        else:
            return hora_atual >= self.horario_abertura or hora_atual <= self.horario_fechamento
    
    @property
    def acesso_bloqueado(self):
        """ Verifica se o restaurante passou da data de validade ou se foi bloqueado manualmente """
        if self.status_assinatura == 'VENCIDO':
            return True
            
        if self.vencimento_assinatura:
            hoje = timezone.localtime().date()
            if hoje > self.vencimento_assinatura:
                return True
                
        return False

    # 🖼️ MÁGICA DE COMPRESSÃO (ECONOMIA DE SERVIDOR)
    def save(self, *args, **kwargs):
        # Se houver um logo e ele não for webp, comprime!
        if self.logo and not self.logo.name.endswith('.webp'):
            self.logo = comprimir_imagem(self.logo)
        super().save(*args, **kwargs)

# --- 1. CATEGORIA ---
class Categoria(models.Model):
    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE)
    nome = models.CharField(max_length=50)
    ordem = models.IntegerField(default=0)
    
    class Meta: 
        ordering = ['ordem']
        
    def __str__(self): 
        return f"{self.nome} ({self.restaurante.nome})"

# --- 2. ADICIONAIS ---
class Adicional(models.Model):
    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE)
    nome = models.CharField(max_length=50, help_text="Ex: Bacon, Ovo, Maionese Extra")
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nome} (+ R$ {self.preco})"

# --- 3. PRODUTO ---
class Produto(models.Model):
    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT)
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    imagem = models.ImageField(upload_to='produtos/', blank=True, null=True)
    ativo = models.BooleanField(default=True)
    tempo_preparo_estimado = models.IntegerField(default=20, help_text="Minutos")
    
    adicionais_disponiveis = models.ManyToManyField(Adicional, blank=True)
    sabores = models.CharField(max_length=500, blank=True, null=True, help_text="Ex: Coxinha, Bolinha de Queijo, Kibe (separe por vírgula)")

    # 🚀 NOVOS CAMPOS PARA O SAAS UNIVERSAL (PIZZARIA, LANCHONETE, AÇAÍ)
    TIPO_ESCOLHA_CHOICES = (
        ('CHECKBOX', 'Múltipla Escolha (Ex: Pizza Meio a Meio, Açaí)'),
        ('QUANTIDADE', 'Quantidade Exata (Ex: 100 Salgadinhos)'),
    )
    tipo_escolha_sabores = models.CharField(
        max_length=15, 
        choices=TIPO_ESCOLHA_CHOICES, 
        default='CHECKBOX', 
        verbose_name="Como o cliente escolhe os Sabores?"
    )
    limite_sabores = models.IntegerField(
        default=2, 
        verbose_name="Limite de Sabores / Quantidade permitida"
    )

    def __str__(self): 
        return self.nome
    
    def save(self, *args, **kwargs):
        # Se houver foto do produto e não for webp, espreme!
        if getattr(self, 'imagem', None) and not self.imagem.name.endswith('.webp'):
            self.imagem = comprimir_imagem(self.imagem)
        super().save(*args, **kwargs)

# --- 4. GESTÃO DE MESAS ---
class Mesa(models.Model):
    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE)
    numero = models.IntegerField()
    qr_code = models.ImageField(upload_to='qrcodes/', blank=True)
    ocupada = models.BooleanField(default=False)

    class Meta:
        # Impede duas Mesas 1 no mesmo restaurante
        unique_together = ('restaurante', 'numero') 

    def __str__(self): 
        return f"Mesa {self.numero} - {self.restaurante.nome}"

# --- 5. LOGÍSTICA ---
class Entregador(models.Model):
    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    celular = models.CharField(max_length=20)
    placa_moto = models.CharField(max_length=10)
    ativo = models.BooleanField(default=True)
    lat_atual = models.CharField(max_length=50, blank=True, null=True)
    long_atual = models.CharField(max_length=50, blank=True, null=True)
    pin = models.CharField(max_length=4, default='1234', help_text="Senha de 4 números para o App")

    def __str__(self): 
        return self.nome

class Bairro(models.Model):
    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE)
    nome = models.CharField(max_length=100)
    taxa = models.DecimalField(max_digits=6, decimal_places=2, default=5.00, verbose_name="Taxa de Entrega (R$)")
    ativo = models.BooleanField(default=True)
    
    ordem_rota = models.IntegerField(
        default=0, 
        verbose_name="Ordem na Rota", 
        help_text="Ex: 1 para o seu bairro, 2 para os vizinhos, 3 para os mais distantes..."
    )

    class Meta:
        ordering = ['ordem_rota', 'nome']

    def __str__(self):
        return f"{self.nome} - R$ {self.taxa}"

# --- 6. PEDIDO ---
class Pedido(models.Model):
    STATUS_CHOICES = (
        ('AGUARDANDO_PAGAMENTO', 'Aguardando Pagamento'),
        ('NOVO', 'Novo Pedido'),
        ('CONFIRMADO', 'Confirmado/Cozinha'),
        ('PRONTO', 'Pronto para Retirada/Entrega'),
        ('EM_TRANSITO', 'Saiu para Entrega'),
        ('AGUARDANDO_CAIXA', 'Aguardando Pagamento na Mesa'),
        ('ENTREGUE', 'Finalizado'),
        ('CANCELADO', 'Cancelado'),
    )
    
    ORIGEM_CHOICES = (
        ('SITE', 'Site/App'),
        ('WHATSAPP', 'Bot WhatsApp'),
        ('MESA', 'Mesa (QR Code)'),
        ('BALCAO', 'Balcão/Caixa'),
    )

    TIPO_ENTREGA_CHOICES = [
        ('ENTREGA', 'Delivery'), 
        ('RETIRADA', 'Retirada na Loja'), 
        ('MESA', 'Servir na Mesa')
    ]

    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE)
    id_pedido = models.UUIDField(default=uuid.uuid4, editable=False)
    
    # 🚀 NOVO CAMPO ADICIONADO: Senha do Dia
    numero_diario = models.IntegerField('Senha do Dia', null=True, blank=True)
    
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES)
    motoboy_lat = models.CharField(max_length=50, blank=True, null=True)
    motoboy_lng = models.CharField(max_length=50, blank=True, null=True)
    cliente_nome = models.CharField(max_length=100, blank=True)
    cliente_whatsapp = models.CharField(max_length=20, blank=True)
    endereco_entrega = models.TextField(blank=True)
    
    mesa = models.ForeignKey(Mesa, on_delete=models.SET_NULL, null=True, blank=True)
    entregador = models.ForeignKey(Entregador, on_delete=models.SET_NULL, null=True, blank=True)
    link_rastreio = models.URLField(blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NOVO')
    forma_pagamento = models.CharField(max_length=50, blank=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    taxa_entrega = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    tipo_entrega = models.CharField(max_length=20, choices=TIPO_ENTREGA_CHOICES, default='ENTREGA')
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self): 
        # Mantido o seu original, mas se quiser pode mudar para exibir o numero_diario
        return f"Pedido #{self.id} - {self.get_status_display()}"

    def avancar_status(self):
        fluxo = {
            'NOVO': 'CONFIRMADO',
            'CONFIRMADO': 'PRONTO',
            'PRONTO': 'EM_TRANSITO',
            'EM_TRANSITO': 'ENTREGUE',
        }
        if self.status in fluxo:
            self.status = fluxo[self.status]
            self.save()
            return self.status
        return None

    def save(self, *args, **kwargs):
        # 🚀 NOVA LÓGICA: Gera a senha sequencial do dia (001, 002...) apenas na criação do pedido
        if not self.pk and not self.numero_diario:
            hoje = timezone.now().date()
            ultimo_pedido_hoje = Pedido.objects.filter(
                restaurante=self.restaurante,
                criado_em__date=hoje
            ).order_by('-numero_diario').first()
            
            if ultimo_pedido_hoje and ultimo_pedido_hoje.numero_diario:
                self.numero_diario = ultimo_pedido_hoje.numero_diario + 1
            else:
                self.numero_diario = 1

        # LÓGICA ORIGINAL MANTIDA INTACTA: Rastreio inteligente
        if not self.link_rastreio and self.restaurante_id:
            # Rastreio inteligente já apontando para o subdomínio/loja do cliente
            self.link_rastreio = f"https://seusite.com/loja/{self.restaurante.slug}/rastreio/{self.id_pedido}"
            
        super().save(*args, **kwargs)

# --- 7. ITEM PEDIDO ---
class ItemPedido(models.Model):
    pedido = models.ForeignKey(Pedido, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    quantidade = models.IntegerField(default=1)
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    adicionais = models.ManyToManyField(Adicional, blank=True)
    observacao = models.TextField(blank=True, help_text="Ex: Sem cebola")

    def __str__(self):
        return f"{self.quantidade}x {self.produto.nome}"

# --- 8. GATILHOS ---
@receiver(post_save, sender=Pedido)
def notificar_robo(sender, instance, created, **kwargs):
    if created:
        print(f"🤖 [ROBÔ {instance.restaurante.nome}]: Novo pedido recebido de {instance.cliente_nome}! Enviando confirmação...")
    else:
        if instance.status == 'EM_TRANSITO':
            print(f"🤖 [ROBÔ {instance.restaurante.nome}]: Olá {instance.cliente_nome}, o motoboy {instance.entregador} saiu! Rastreie aqui: {instance.link_rastreio}")

# ==========================================
# 9. GESTÃO DE CAIXA (FINANCEIRO SAAS)
# ==========================================
class Caixa(models.Model):
    STATUS_CHOICES = (
        ('ABERTO', 'Aberto'),
        ('FECHADO', 'Fechado'),
    )
    
    restaurante = models.ForeignKey(Restaurante, on_delete=models.CASCADE)
    operador = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    data_abertura = models.DateTimeField(auto_now_add=True)
    data_fechamento = models.DateTimeField(null=True, blank=True)
    saldo_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ABERTO')

    def __str__(self):
        return f"Caixa {self.id} ({self.restaurante.nome}) - {self.status}"

class MovimentacaoCaixa(models.Model):
    TIPO_CHOICES = (
        ('ENTRADA', 'Entrada (Venda/Suprimento)'),
        ('SAIDA', 'Saída (Sangria/Pagamento)'),
    )
    
    caixa = models.ForeignKey(Caixa, on_delete=models.CASCADE, related_name='movimentacoes')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    descricao = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    forma_pagamento = models.CharField(max_length=50, default='DINHEIRO')
    data = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tipo} - R$ {self.valor}"