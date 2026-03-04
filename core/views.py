import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDay, TruncDate
from django.utils import timezone
from .forms import ProdutoForm
import qrcode
from io import BytesIO
from django.db import transaction
import mercadopago
from django.contrib import messages
from .models import Pedido, ItemPedido, Produto, Mesa, Adicional, Categoria, Caixa, MovimentacaoCaixa, Restaurante, Bairro, Entregador
from .services import disparar_whatsapp_async
from .forms import RestauranteForm
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.utils.text import slugify
from datetime import timedelta

# ==========================================
# 1. PÚBLICO (CLIENTE)
# ==========================================

# ==========================================
# 🚀 PÁGINA DE VENDAS DO SAAS (ALIANCEFOOD)
# ==========================================
def landing_page(request):
    if request.method == 'POST':
        nome_loja = request.POST.get('nome_loja')
        email = request.POST.get('email')
        senha = request.POST.get('senha')
        telefone = request.POST.get('telefone')

        # 1. Verifica se o email já existe
        if User.objects.filter(username=email).exists():
            messages.error(request, "Este e-mail já está em uso! Tente outro ou faça login.")
            return redirect('landing_page')

        # 2. Cria o Utilizador (Dono da Loja)
        user = User.objects.create_user(username=email, email=email, password=senha)
        
        # 3. Gera o Link da Loja Automático (Ex: "Rei do Hambúrguer" vira "rei-do-hamburguer")
        slug_base = slugify(nome_loja)
        slug_final = slug_base
        contador = 1
        while Restaurante.objects.filter(slug=slug_final).exists():
            slug_final = f"{slug_base}-{contador}"
            contador += 1
        
        # 4. A MÁGICA DOS 24 HORAS (Validade = Hoje + 1 dia)
        vencimento = timezone.localtime().date() + timedelta(days=1)
        
        # 5. Cria a Loja Oficial
        restaurante = Restaurante.objects.create(
            dono=user,
            nome=nome_loja,
            slug=slug_final,
            telefone=telefone,
            status_assinatura='TRIAL',
            vencimento_assinatura=vencimento
        )
        
        # 6. Faz o login automático e envia-o para o Dashboard
        login(request, user)
        return redirect('dashboard') # ATENÇÃO: Confirme se o nome da sua URL do dashboard é 'dashboard'

    return render(request, 'core/landing.html')

# 🚀 SaaS: A função agora exige o 'slug' (link único da lanchonete)
def index(request, slug):
    # 🚀 SaaS: Pega APENAS a lanchonete dona deste link
    restaurante_atual = get_object_or_404(Restaurante, slug=slug)

    # 🪓 A GUILHOTINA ENTRA AQUI! 🪓 (Nova Configuração de Bloqueio SaaS)
    if restaurante_atual.acesso_bloqueado:
        return render(request, 'core/loja_bloqueada.html', {'restaurante': restaurante_atual})

    mesa_id = request.GET.get('mesa')
    mesa_obj = None
    if mesa_id:
        try:
            # 🚀 SaaS: Garante que a mesa pertence a este restaurante
            mesa_obj = Mesa.objects.get(numero=mesa_id, restaurante=restaurante_atual)
        except Mesa.DoesNotExist: pass

    # 🚀 SaaS: Puxa APENAS as categorias desta lanchonete
    categorias = Categoria.objects.filter(restaurante=restaurante_atual).prefetch_related('produto_set')
    
    contexto = { 
        'categorias': categorias, 
        'mesa': mesa_obj,
        'config': restaurante_atual  # 🚀 SaaS: Mandando a configuração específica do inquilino
    }
    return render(request, 'core/index.html', contexto)

# 🚀 SaaS: Exige o slug para não misturar os rastreios
def rastreio_pedido(request, slug, pedido_id):
    restaurante_atual = get_object_or_404(Restaurante, slug=slug)
    pedido = get_object_or_404(Pedido, id_pedido=pedido_id, restaurante=restaurante_atual)
    
    status_percent = {
        'NOVO': 10, 'CONFIRMADO': 30, 'PRONTO': 60, 
        'EM_TRANSITO': 85, 'ENTREGUE': 100
    }
    
    contexto = {
        'pedido': pedido,
        'progresso': status_percent.get(pedido.status, 0),
        # 🚀 SaaS: Nasce na coordenada específica DESTA lanchonete
        'lat_inicial': pedido.motoboy_lat if pedido.motoboy_lat else restaurante_atual.lat_padrao,
        'lng_inicial': pedido.motoboy_lng if pedido.motoboy_lng else restaurante_atual.lng_padrao,
        'config': restaurante_atual
    }
    return render(request, 'core/rastreio.html', contexto)

# ==========================================
# 2. APIs CRÍTICAS (BLINDADAS)
# ==========================================

@csrf_exempt
@transaction.atomic
def api_finalizar(request):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            
            # 🚀 SaaS: A API agora precisa saber DE QUEM é o pedido
            restaurante_id = dados.get('restaurante_id')
            if not restaurante_id:
                return JsonResponse({'status': 'erro', 'msg': 'Restaurante não identificado na transação.'})
            restaurante = get_object_or_404(Restaurante, id=restaurante_id)

            forma_pgto = dados.get('forma_pagamento', 'PIX')
            origem_req = dados.get('origem', 'SITE')
            tipo_entrega_req = dados.get('tipo_entrega', 'ENTREGA')
            bairro_id = dados.get('bairro_id')
            mesa_numero = dados.get('mesa_id')
            
            valor_taxa = 0.00
            endereco_final = dados.get('endereco', '')

            if tipo_entrega_req == 'ENTREGA' and origem_req not in ['MESA', 'BALCAO'] and not mesa_numero:
                if bairro_id:
                    # 🚀 SaaS: Filtra o bairro da lanchonete certa
                    bairro = get_object_or_404(Bairro, id=bairro_id, restaurante=restaurante)
                    valor_taxa = float(bairro.taxa)
                    endereco_final = f"Bairro: {bairro.nome}\nEndereço: {endereco_final}"
                else:
                    return JsonResponse({'status': 'erro', 'msg': 'Selecione um bairro para a entrega.'})
            
            if mesa_numero or origem_req in ['MESA', 'BALCAO'] or tipo_entrega_req == 'RETIRADA':
                valor_taxa = 0.00
                if mesa_numero or origem_req == 'MESA':
                    tipo_entrega_req = 'MESA'

            status_inicial = 'AGUARDANDO_PAGAMENTO' if forma_pgto == 'PIX' else 'NOVO'
            
            novo_pedido = Pedido.objects.create(
                restaurante=restaurante, # 🚀 SaaS: Carimba o pedido como pertencente a este inquilino
                cliente_nome=dados.get('nome', 'Cliente Não Identificado'),
                cliente_whatsapp=dados.get('whatsapp', ''),
                endereco_entrega=endereco_final,
                forma_pagamento=forma_pgto,
                origem=origem_req,
                status=status_inicial,
                taxa_entrega=valor_taxa,
                tipo_entrega=tipo_entrega_req 
            )

            if mesa_numero:
                mesa = get_object_or_404(Mesa.objects.select_for_update(), numero=mesa_numero, restaurante=restaurante)
                novo_pedido.mesa = mesa
                novo_pedido.origem = 'MESA'
                novo_pedido.save()

            total_pedido = 0

            for item in dados.get('itens', []):
                if 'id' in item:
                    produto = get_object_or_404(Produto, id=item['id'], restaurante=restaurante)
                else:
                    produto = get_object_or_404(Produto, nome=item['name'], restaurante=restaurante)
                
                novo_item = ItemPedido.objects.create(
                    pedido=novo_pedido,
                    produto=produto,
                    quantidade=item['qty'],
                    preco_unitario=produto.preco,
                    observacao=item.get('obs', '')
                )
                
                total_item = float(produto.preco) * int(item['qty'])
                
                if 'adicionais_ids' in item:
                    for add_id in item['adicionais_ids']:
                        adicional = get_object_or_404(Adicional, id=add_id, restaurante=restaurante)
                        novo_item.adicionais.add(adicional)
                        total_item += (float(adicional.preco) * int(item['qty']))
                
                total_pedido += total_item

            total_pedido += float(valor_taxa)
            novo_pedido.total = total_pedido
            novo_pedido.save()

            if novo_pedido.origem == 'BALCAO':
                caixa_aberto = Caixa.objects.filter(status='ABERTO', restaurante=restaurante).last()
                if caixa_aberto:
                    MovimentacaoCaixa.objects.create(
                        caixa=caixa_aberto, tipo='ENTRADA',
                        descricao=f'Venda Balcão #{novo_pedido.numero_diario:03d}',
                        valor=novo_pedido.total, forma_pagamento=forma_pgto
                    )

            qr_code_base64 = ""
            qr_code_copia_cola = ""

            if forma_pgto == 'PIX':
                # 🚀 SaaS: Usa a chave do Mercado Pago específica DESTE restaurante
                if not restaurante.mp_access_token:
                    return JsonResponse({'status': 'erro', 'msg': 'Loja sem PIX configurado no momento.'})

                if total_pedido < 0.01:
                    total_pedido = 0.01

                sdk = mercadopago.SDK(restaurante.mp_access_token) 
                host_atual = request.get_host()

                payment_data = {
                    "transaction_amount": float(total_pedido),
                    "description": f"Pedido #{novo_pedido.numero_diario:03d} - {restaurante.nome}",
                    "payment_method_id": "pix",
                    "external_reference": str(novo_pedido.id),
                    "payer": {
                        "email": "cliente@sandbox.com",
                        "first_name": novo_pedido.cliente_nome.split()[0] if novo_pedido.cliente_nome else "Cliente"
                    },
                    "notification_url": f"https://{host_atual}/api/webhook/mercadopago/"
                }
                
                result = sdk.payment().create(payment_data)
                payment = result.get("response", {})
                
                if "point_of_interaction" in payment:
                    transaction_data = payment["point_of_interaction"]["transaction_data"]
                    qr_code_base64 = transaction_data.get("qr_code_base64", "")
                    qr_code_copia_cola = transaction_data.get("qr_code", "")
                else:
                    print("❌ ERRO NO MERCADO PAGO:", payment)
                    return JsonResponse({'status': 'erro', 'msg': 'O banco demorou a responder. Tente novamente!'})

            if novo_pedido.cliente_whatsapp and restaurante.ultramsg_instance:
                host = request.get_host()
                link = f"http://{host}/loja/{restaurante.slug}/rastreio/{novo_pedido.id_pedido}/"
                
                if novo_pedido.origem == 'MESA' or novo_pedido.mesa:
                    msg = (f"Olá, {novo_pedido.cliente_nome}! 🍔\n\n"
                           f"Seu pedido *#{novo_pedido.numero_diario:03d}* já foi enviado para a chapa!\n"
                           f"📍 Ele será servido na sua *Mesa {novo_pedido.mesa.numero}* em breve.\n\n"
                           f"Bom apetite!")
                    disparar_whatsapp_async(novo_pedido.cliente_whatsapp, msg, restaurante)
                else:
                    if forma_pgto == 'PIX':
                        msg = (f"Olá, {novo_pedido.cliente_nome}! 🍔\n\nRecebemos seu pedido *#{novo_pedido.numero_diario:03d}*!\n"
                               f"⏳ Estamos apenas *aguardando o pagamento do PIX* para enviá-lo para a chapa.\n\n"
                               f"Acompanhe e veja o QR Code aqui: {link}")
                    else:
                        msg = (f"Olá, {novo_pedido.cliente_nome}! 🍔\n\nSeu pedido *#{novo_pedido.numero_diario:03d}* foi recebido e já vai para a chapa!\n"
                               f"📍 Acompanhe pelo link: {link}")
                    disparar_whatsapp_async(novo_pedido.cliente_whatsapp, msg, restaurante)

            return JsonResponse({
                'status': 'sucesso', 
                'pedido_id': f"{novo_pedido.numero_diario:03d}", 
                'id_rastreio': str(novo_pedido.id_pedido),
                'forma_pagamento': forma_pgto,
                'qr_code_base64': qr_code_base64,
                'qr_code_copia_cola': qr_code_copia_cola,
                'slug_loja': restaurante.slug # 🚀 Devolve o slug para o redirect funcionar
            })
            
        except Exception as e:
            return JsonResponse({'status': 'erro', 'msg': 'Falha ao processar: ' + str(e)})

    return JsonResponse({'status': 'erro'}, status=400)

@csrf_exempt
@transaction.atomic
def api_fechar_mesa(request, mesa_id):
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            # 🚀 SaaS: Precisa do restaurante
            restaurante_id = dados.get('restaurante_id')
            restaurante = get_object_or_404(Restaurante, id=restaurante_id)

            mesa = get_object_or_404(Mesa.objects.select_for_update(), numero=mesa_id, restaurante=restaurante)
            
            pedidos = Pedido.objects.filter(
                mesa=mesa, status__in=['NOVO', 'CONFIRMADO', 'PRONTO', 'EM_TRANSITO', 'ENTREGUE', 'AGUARDANDO_CAIXA']
            ).select_for_update()
            
            if not pedidos.exists():
                return JsonResponse({'status': 'erro', 'msg': 'A sua mesa está vazia ou já foi encerrada.'})

            total_pago = sum(p.total for p in pedidos)

            for p in pedidos:
                p.status = 'AGUARDANDO_CAIXA'
                p.save()
            
            return JsonResponse({'status': 'sucesso', 'msg': f'A sua conta deu R$ {total_pago:.2f}.'})

        except Exception as e:
            return JsonResponse({'status': 'erro', 'msg': str(e)}, status=500)
            
    return JsonResponse({'status': 'erro'}, status=400)

@csrf_exempt
def webhook_mercadopago(request):
    print("\n🛎️ --- WEBHOOK ACIONADO PELO MERCADO PAGO! ---")
    if request.method == 'POST':
        try:
            dados = request.GET.dict()
            if not dados:
                dados = json.loads(request.body)
            
            print("📦 Dados recebidos:", dados)
            payment_id = dados.get('data', {}).get('id') or dados.get('data.id')
            
            if (dados.get('type') == 'payment' or dados.get('action') in ['payment.updated', 'payment.created']) and payment_id:
                print(f"🔍 ID do Pagamento no MP: {payment_id}")
                
                # 🚀 SaaS: Tentamos usar o primeiro token válido da base para consultar o MP
                # Numa versão avançada de OAuth, isto muda, mas garante o funcionamento agora.
                token_valido = Restaurante.objects.exclude(mp_access_token__isnull=True).first()
                sdk_token = token_valido.mp_access_token if token_valido else "APP_USR-6237062141884906-021814-a34559040cdd3c5c2c02badc909ec6d4-1242834927"
                
                sdk = mercadopago.SDK(sdk_token)
                payment_info = sdk.payment().get(payment_id)
                
                if payment_info["status"] == 200:
                    pagamento = payment_info["response"]
                    status_pgto = pagamento["status"]
                    pedido_id = str(pagamento.get("external_reference"))
                    
                    print(f"💳 Status no MP: {status_pgto} | Referência: {pedido_id}")
                    
                    if status_pgto == "approved" and pedido_id:
                        
                        # 🚀 1. NOVA CONFIGURAÇÃO SAAS (Renovação Automática)
                        if pedido_id.startswith("SAAS_"):
                            restaurante_id = pedido_id.split("_")[1]
                            restaurante = Restaurante.objects.filter(id=restaurante_id).first()
                            
                            if restaurante:
                                hoje = timezone.localtime().date()
                                if restaurante.vencimento_assinatura is None or restaurante.vencimento_assinatura < hoje:
                                    restaurante.vencimento_assinatura = hoje + timedelta(days=30)
                                else:
                                    restaurante.vencimento_assinatura += timedelta(days=30)
                                
                                restaurante.status_assinatura = 'ATIVO'
                                restaurante.save()
                                print(f"✅🤑 DINHEIRO NA CONTA! Assinatura do {restaurante.nome} renovada para {restaurante.vencimento_assinatura}!")

                        # 🍔 2. O SEU CÓDIGO INTACTO DA MESA (Apenas virou elif)
                        elif pedido_id.startswith("MESA_"):
                            mesa_id = pedido_id.split("_")[1]
                            mesa = Mesa.objects.filter(id=mesa_id).first()
                            
                            if mesa:
                                pedidos_abertos = Pedido.objects.filter(mesa=mesa, status__in=['NOVO', 'CONFIRMADO', 'PRONTO', 'EM_TRANSITO', 'ENTREGUE', 'AGUARDANDO_CAIXA'])
                                total_pago = sum(p.total for p in pedidos_abertos)
                                
                                if pedidos_abertos.exists():
                                    caixa_aberto = Caixa.objects.filter(status='ABERTO', restaurante=mesa.restaurante).last()
                                    if caixa_aberto and total_pago > 0:
                                        MovimentacaoCaixa.objects.create(
                                            caixa=caixa_aberto, tipo='ENTRADA',
                                            descricao=f'PIX Automático (Mesa {mesa.numero})',
                                            valor=total_pago, forma_pagamento='PIX'
                                        )
                                    
                                    pedidos_abertos.update(status='FINALIZADO', forma_pagamento='PIX')
                                    mesa.ocupada = False
                                    mesa.save()
                                    print(f"✅ SUCESSO! A Mesa {mesa.numero} pagou o PIX e foi libertada!")
                                else:
                                    print("⚠️ A mesa não tinha pedidos abertos para finalizar.")
                        
                        # 🛵 3. O SEU CÓDIGO INTACTO DO PEDIDO NORMAL
                        else:
                            pedido = Pedido.objects.filter(id=pedido_id).first()
                            if pedido:
                                print(f"🍔 Pedido #{pedido.numero_diario:03d} encontrado! Status antigo: {pedido.status}")
                                if pedido.status == 'AGUARDANDO_PAGAMENTO':
                                    pedido.status = 'NOVO'
                                    pedido.save()
                                    print("✅ STATUS MUDOU PARA 'NOVO'! (Enviado para a Cozinha)")
                                    
                                    caixa_aberto = Caixa.objects.filter(status='ABERTO', restaurante=pedido.restaurante).last()
                                    if caixa_aberto:
                                        MovimentacaoCaixa.objects.create(
                                            caixa=caixa_aberto, tipo='ENTRADA',
                                            descricao=f'PIX Automático #{pedido.numero_diario:03d}',
                                            valor=pedido.total, forma_pagamento='PIX'
                                        )
                                    
                                    if pedido.cliente_whatsapp and pedido.restaurante.ultramsg_instance:
                                        host = request.get_host()
                                        link = f"http://{host}/loja/{pedido.restaurante.slug}/rastreio/{pedido.id_pedido}/"
                                        msg = f"💸 *PIX Recebido!* \n\nOpa {pedido.cliente_nome}, o dinheiro caiu na conta! Já mandamos o seu pedido #{pedido.numero_diario:03d} pra chapa. 🍔🔥\n\nAcompanhe no mapa: {link}"
                                        disparar_whatsapp_async(pedido.cliente_whatsapp, msg, pedido.restaurante)
                                else:
                                    print("⚠️ O pedido ignorou porque já não estava 'AGUARDANDO_PAGAMENTO'.")
                            else:
                                print(f"❌ Pedido {pedido_id} não encontrado no banco de dados.")
                else:
                    print("❌ Erro ao consultar o Mercado Pago:", payment_info)
                    
            return HttpResponse(status=200)
        except Exception as e:
            print("❌ Erro grave no Webhook:", e)
            return HttpResponse(status=500)
            
    return HttpResponse(status=200)
# ==========================================
# 3. APIs DE LOGÍSTICA E COZINHA (BLINDADAS)
# ==========================================

@login_required(login_url='/accounts/login/')
def api_alterar_status(request, pedido_id):
    if request.method == 'POST':
        # 🚀 SaaS: Confirma que o pedido pertence ao dono logado
        pedido = get_object_or_404(Pedido, id=pedido_id, restaurante=request.user.restaurante_saas)
        novo_status = None
        
        if request.body:
            try:
                data = json.loads(request.body)
                novo_status = data.get('status')
            except: pass
                
        if not novo_status and 'status' in request.POST:
            novo_status = request.POST.get('status')
            
        if not novo_status:
            novo_status = pedido.avancar_status()
        else:
            pedido.status = novo_status
            pedido.save()
            
        if pedido.cliente_whatsapp and pedido.restaurante.ultramsg_instance:
            host = request.get_host()
            link = f"http://{host}/loja/{pedido.restaurante.slug}/rastreio/{pedido.id_pedido}"
            
            if novo_status == 'CONFIRMADO':
                msg = f"👨‍🍳 *Abaixa que é tiro!* Seu pedido #{pedido.numero_diario:03d} acabou de ir pra chapa, {pedido.cliente_nome}!\n\nAcompanhe aqui: {link}"
                disparar_whatsapp_async(pedido.cliente_whatsapp, msg, pedido.restaurante)
                
            elif novo_status == 'PRONTO':
                if pedido.origem == 'MESA' or pedido.mesa:
                    msg = f"🛎️ *Saindo!* O seu lanche está pronto e já está a caminho da sua Mesa {pedido.mesa.numero}, {pedido.cliente_nome}! 🍔"
                else:
                    msg = f"📦 *Prontinho!* Seu pedido #{pedido.numero_diario:03d} está embalado e aguardando o motoboy iniciar a rota de entrega!\n\n📍 Acompanhe: {link}"
                disparar_whatsapp_async(pedido.cliente_whatsapp, msg, pedido.restaurante)

            elif novo_status == 'EM_TRANSITO':
                if pedido.origem == 'MESA' or pedido.mesa:
                    msg = f"🍽️ *Servido!* Seu pedido chegou na mesa, {pedido.cliente_nome}. Bom apetite! Qualquer coisa é só nos chamar."
                else:
                    msg = f"🛵 *VRUUUM!* Seu pedido saiu para entrega, {pedido.cliente_nome}!\n\nAbra o link abaixo para ver o motoboy no mapa em tempo real:\n📍 {link}"
                disparar_whatsapp_async(pedido.cliente_whatsapp, msg, pedido.restaurante)

        return JsonResponse({'status': 'ok'})
        
    return JsonResponse({'status': 'erro'}, status=400)


@csrf_exempt
def api_assumir_entrega(request, pedido_id):
    if request.method == 'POST':
        pedido = get_object_or_404(Pedido, id=pedido_id)
        
        pedido.status = 'EM_TRANSITO'
        pedido.save()
        
        if pedido.cliente_whatsapp and pedido.restaurante.ultramsg_instance:
            host = request.get_host()
            link = f"http://{host}/loja/{pedido.restaurante.slug}/rastreio/{pedido.id_pedido}"
            msg = f"🛵 *VRUUUM!* Seu pedido saiu para entrega, {pedido.cliente_nome}!\n\nAbra o link abaixo para ver o motoboy no mapa em tempo real:\n📍 {link}"
            disparar_whatsapp_async(pedido.cliente_whatsapp, msg, pedido.restaurante)
            
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'erro'}, status=400)

@csrf_exempt
def api_salvar_gps(request, pedido_id):
    if request.method == 'POST':
        try:
            pedido = Pedido.objects.get(id=pedido_id)
            data = json.loads(request.body)
            pedido.motoboy_lat = data.get('lat')
            pedido.motoboy_lng = data.get('lng')
            pedido.save()
            return JsonResponse({'status': 'ok'})
        except Pedido.DoesNotExist:
            return JsonResponse({'status': 'erro'})
    return JsonResponse({'status': 'erro'}, status=400)

# ==========================================
# 4. PAINÉIS DE ADMINISTRAÇÃO E PDV
# ==========================================

@login_required(login_url='/accounts/login/')
def painel_caixa(request):
    # 🚀 SaaS: Pega a loja do usuário logado
    restaurante = request.user.restaurante_saas
    caixa_aberto = Caixa.objects.filter(status='ABERTO', restaurante=restaurante).last()
    
    if request.method == 'POST':
        acao = request.POST.get('acao')
        
        if acao == 'abrir' and not caixa_aberto:
            saldo_inicial = float(request.POST.get('saldo_inicial', 0).replace(',', '.'))
            caixa_aberto = Caixa.objects.create(
                restaurante=restaurante, # 🚀
                operador=request.user,
                saldo_inicial=saldo_inicial,
                status='ABERTO'
            )
            if saldo_inicial > 0:
                MovimentacaoCaixa.objects.create(
                    caixa=caixa_aberto, tipo='ENTRADA', descricao='Troco Inicial (Abertura)',
                    valor=saldo_inicial, forma_pagamento='DINHEIRO'
                )
            return redirect('painel_caixa')

        elif acao == 'movimentar' and caixa_aberto:
            tipo = request.POST.get('tipo') 
            valor = float(request.POST.get('valor', 0).replace(',', '.'))
            descricao = request.POST.get('descricao', 'Movimentação manual')
            forma_pgto = request.POST.get('forma_pagamento', 'DINHEIRO')
            
            MovimentacaoCaixa.objects.create(
                caixa=caixa_aberto, tipo=tipo, descricao=descricao,
                valor=valor, forma_pagamento=forma_pgto
            )
            return redirect('painel_caixa')

        elif acao == 'fechar' and caixa_aberto:
            caixa_aberto.status = 'FECHADO'
            caixa_aberto.data_fechamento = timezone.now()
            caixa_aberto.save()
            return redirect('painel_caixa')

    resumo = {'PIX': 0, 'CARTAO': 0, 'DINHEIRO': 0, 'TOTAL': 0, 'RETIRADAS': 0}
    movimentacoes = []
    
    if caixa_aberto:
        movs = caixa_aberto.movimentacoes.all().order_by('-data')
        movimentacoes = movs
        
        for m in movs:
            if m.tipo == 'ENTRADA':
                resumo[m.forma_pagamento] = resumo.get(m.forma_pagamento, 0) + float(m.valor)
                resumo['TOTAL'] += float(m.valor)
            elif m.tipo == 'SAIDA':
                resumo['RETIRADAS'] += float(m.valor)
                if m.forma_pagamento == 'DINHEIRO':
                    resumo['DINHEIRO'] -= float(m.valor)
                    resumo['TOTAL'] -= float(m.valor)

    contexto = {
        'caixa': caixa_aberto,
        'resumo': resumo,
        'movimentacoes': movimentacoes,
        'restaurante': restaurante
    }
    return render(request, 'core/gestao_caixa.html', contexto)

@login_required(login_url='/accounts/login/')
def painel_cozinha(request):
    restaurante = request.user.restaurante_saas
    pedidos = Pedido.objects.filter(restaurante=restaurante, status__in=['NOVO', 'CONFIRMADO', 'PRONTO']).order_by('criado_em')
    return render(request, 'core/cozinha.html', {'pedidos': pedidos, 'restaurante': restaurante})

@login_required(login_url='/accounts/login/')
def caixa_balcao(request):
    restaurante = request.user.restaurante_saas
    categorias = Categoria.objects.filter(restaurante=restaurante).prefetch_related('produto_set')
    mesas = Mesa.objects.filter(restaurante=restaurante)
    return render(request, 'core/caixa.html', {'categorias': categorias, 'mesas': mesas, 'restaurante': restaurante})

@login_required(login_url='/accounts/login/')
def dashboard(request):
    restaurante = request.user.restaurante_saas
    hoje = timezone.now().date()
    
    # 🚀 SaaS: Filtra apenas os pedidos desta lanchonete
    pedidos_da_loja = Pedido.objects.filter(restaurante=restaurante, criado_em__date=hoje)
    
    faturamento = pedidos_da_loja.filter(status__in=['ENTREGUE', 'EM_TRANSITO', 'FINALIZADO']).aggregate(Sum('total'))['total__sum'] or 0
    qtde_pedidos = pedidos_da_loja.count()
    ticket_medio = faturamento / qtde_pedidos if qtde_pedidos > 0 else 0

    pedidos_novos = pedidos_da_loja.filter(status='NOVO').order_by('criado_em')
    pedidos_cozinha = pedidos_da_loja.filter(status='CONFIRMADO').order_by('criado_em')
    pedidos_prontos = pedidos_da_loja.filter(status='PRONTO').order_by('criado_em')
    entregas_rua = Pedido.objects.filter(restaurante=restaurante, status='EM_TRANSITO').order_by('-atualizado_em')

    vendas_semana = Pedido.objects.filter(restaurante=restaurante, status__in=['ENTREGUE', 'FINALIZADO']).annotate(dia=TruncDay('criado_em')).values('dia').annotate(total=Sum('total')).order_by('dia')[:7]
    datas = [v['dia'].strftime('%d/%m') for v in vendas_semana]
    valores = [float(v['total']) for v in vendas_semana]

    top_produtos = ItemPedido.objects.filter(pedido__restaurante=restaurante).values('produto__nome').annotate(qtd=Sum('quantidade')).order_by('-qtd')[:5]
    nomes_prod = [p['produto__nome'] for p in top_produtos]
    qtd_prod = [p['qtd'] for p in top_produtos]

    contexto = {
        'fat_hoje': faturamento, 'pedidos_hoje': qtde_pedidos, 'ticket_medio': ticket_medio,
        'pedidos_novos': pedidos_novos, 'pedidos_cozinha': pedidos_cozinha,
        'pedidos_prontos': pedidos_prontos, 'entregas_rua': entregas_rua,
        'grafico_datas': json.dumps(datas), 'grafico_valores': json.dumps(valores),
        'prod_labels': json.dumps(nomes_prod), 'prod_valores': json.dumps(qtd_prod),
        'restaurante': restaurante
    }
    return render(request, 'core/dashboard.html', contexto)

@login_required(login_url='/accounts/login/')
def imprimir_cupom(request, pedido_id):
    restaurante = request.user.restaurante_saas
    pedido = get_object_or_404(Pedido, id=pedido_id, restaurante=restaurante)
    contexto = { 'pedido': pedido, 'data_hora': timezone.localtime(pedido.criado_em).strftime("%d/%m/%Y %H:%M") }
    return render(request, 'core/imprimir.html', contexto)

# ==========================================
# 5. VIEWS HTMX (DASHBOARD AO VIVO)
# ==========================================

@login_required(login_url='/accounts/login/')
def htmx_dashboard_kpis(request):
    restaurante = request.user.restaurante_saas
    hoje = timezone.now().date()
    pedidos = Pedido.objects.filter(restaurante=restaurante, criado_em__date=hoje)
    faturamento = pedidos.filter(status__in=['ENTREGUE', 'EM_TRANSITO', 'FINALIZADO']).aggregate(Sum('total'))['total__sum'] or 0
    qtde_pedidos = pedidos.count()
    ticket_medio = faturamento / qtde_pedidos if qtde_pedidos > 0 else 0
    return render(request, 'core/partials/h_kpis.html', {'fat_hoje': faturamento, 'pedidos_hoje': qtde_pedidos, 'ticket_medio': ticket_medio})

@login_required(login_url='/accounts/login/')
def htmx_dashboard_novos(request):
    restaurante = request.user.restaurante_saas
    hoje = timezone.now().date()
    pedidos = Pedido.objects.filter(restaurante=restaurante, status='NOVO', criado_em__date=hoje).order_by('criado_em')
    return render(request, 'core/partials/h_novos.html', {'pedidos_novos': pedidos})

@login_required(login_url='/accounts/login/')
def htmx_dashboard_cozinha(request):
    restaurante = request.user.restaurante_saas
    hoje = timezone.now().date()
    pedidos = Pedido.objects.filter(restaurante=restaurante, status='CONFIRMADO', criado_em__date=hoje).order_by('criado_em')
    return render(request, 'core/partials/h_cozinha.html', {'pedidos_cozinha': pedidos})

@login_required(login_url='/accounts/login/')
def htmx_dashboard_logistica(request):
    restaurante = request.user.restaurante_saas
    entregas = Pedido.objects.filter(restaurante=restaurante, status='EM_TRANSITO').exclude(origem__in=['MESA', 'BALCAO']).order_by('-atualizado_em')
    return render(request, 'core/partials/h_logistica.html', {'entregas_rua': entregas})

# ==========================================
# 6. GESTÃO DE CARDÁPIO E MESAS
# ==========================================

@login_required(login_url='/accounts/login/')
def gerenciar_cardapio(request):
    restaurante = request.user.restaurante_saas
    produtos = Produto.objects.filter(restaurante=restaurante).order_by('categoria', 'nome')
    categorias = Categoria.objects.filter(restaurante=restaurante)
    
    # 🚀 SAAS: Enviando o restaurante para o Form filtrar as categorias e adicionais!
    form = ProdutoForm(request.POST or None, request.FILES or None, restaurante=restaurante)
    
    if request.method == 'POST' and form.is_valid():
        prod = form.save(commit=False)
        prod.restaurante = restaurante
        prod.save()
        form.save_m2m() # Salva as tags de múltiplos (adicionais e sabores)
        return redirect('gerenciar_cardapio')
        
    return render(request, 'core/cardapio_admin.html', {
        'produtos': produtos, 
        'categorias': categorias, 
        'form': form, 
        'restaurante': restaurante
    })

@login_required(login_url='/accounts/login/')
def editar_produto(request, produto_id):
    restaurante = request.user.restaurante_saas
    produto = get_object_or_404(Produto, id=produto_id, restaurante=restaurante)
    
    # 🚀 SAAS: Injetando o restaurante na edição também!
    form = ProdutoForm(request.POST or None, request.FILES or None, instance=produto, restaurante=restaurante)
    
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('gerenciar_cardapio')
        
    return render(request, 'core/partials/modal_produto.html', {
        'form': form, 
        'produto': produto
    })

@login_required(login_url='/accounts/login/')
@csrf_exempt
def api_toggle_produto(request, produto_id):
    if request.method == 'POST':
        restaurante = request.user.restaurante_saas
        prod = get_object_or_404(Produto, id=produto_id, restaurante=restaurante)
        prod.ativo = not prod.ativo
        prod.save()
        return JsonResponse({'status': 'ok', 'ativo': prod.ativo})
    return JsonResponse({'status': 'erro'})

@login_required(login_url='/accounts/login/')
def gerenciar_mesas(request):
    restaurante = request.user.restaurante_saas
    if Mesa.objects.filter(restaurante=restaurante).count() == 0:
        for i in range(1, 11): Mesa.objects.create(numero=i, restaurante=restaurante)
            
    todas_mesas = Mesa.objects.filter(restaurante=restaurante).order_by('numero')
    mesas_status = []

    for mesa in todas_mesas:
        pedidos_abertos = Pedido.objects.filter(
            mesa=mesa, 
            status__in=['NOVO', 'CONFIRMADO', 'PRONTO', 'EM_TRANSITO', 'ENTREGUE', 'AGUARDANDO_CAIXA'] 
        ).exclude(status='FINALIZADO')

        total = pedidos_abertos.aggregate(Sum('total'))['total__sum'] or 0
        mesas_status.append({'obj': mesa, 'ocupada': pedidos_abertos.exists(), 'total': total, 'pedidos': pedidos_abertos.count()})

    return render(request, 'core/mesas.html', {'mesas': mesas_status, 'restaurante': restaurante})

@login_required(login_url='/accounts/login/')
def gerar_qrcode(request, mesa_id):
    restaurante = request.user.restaurante_saas
    mesa = get_object_or_404(Mesa, id=mesa_id, restaurante=restaurante)
    host = request.get_host()
    # 🚀 SaaS: O QR Code agora direciona para o link exclusivo da lanchonete
    link = f"http://{host}/loja/{restaurante.slug}/?mesa={mesa.numero}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    response = HttpResponse(content_type="image/png")
    img.save(response, "PNG")
    return response

@login_required(login_url='/accounts/login/')
def api_detalhes_mesa(request, mesa_id):
    restaurante = request.user.restaurante_saas
    mesa = get_object_or_404(Mesa, numero=mesa_id, restaurante=restaurante)
    pedidos = Pedido.objects.filter(mesa=mesa, status__in=['NOVO', 'CONFIRMADO', 'PRONTO', 'EM_TRANSITO', 'ENTREGUE', 'AGUARDANDO_CAIXA'])
    itens_resumo = []
    total_geral = 0
    
    for p in pedidos:
        for item in p.itens.all():
            total_geral += (item.preco_unitario * item.quantidade)
            for add in item.adicionais.all():
                total_geral += (add.preco * item.quantidade)
            itens_resumo.append({'produto': item.produto.nome, 'qtd': item.quantidade, 'total': (item.preco_unitario * item.quantidade)})
            
    return JsonResponse({'mesa': mesa.numero, 'itens': itens_resumo, 'total': total_geral})

@login_required(login_url='/accounts/login/')
def api_listar_mesas_aguardando(request):
    restaurante = request.user.restaurante_saas
    mesas = Pedido.objects.filter(restaurante=restaurante, status='AGUARDANDO_CAIXA', mesa__isnull=False) \
                          .values('mesa__numero') \
                          .annotate(total_pendente=Sum('total'), qtd=Count('id'))
    lista = []
    for m in mesas:
        lista.append({
            'mesa': m['mesa__numero'],
            'total': float(m['total_pendente']),
            'qtd': m['qtd']
        })
    return JsonResponse({'mesas': lista})

@login_required(login_url='/accounts/login/')
def api_gerar_pix_operador(request, mesa_numero):
    try:
        restaurante = request.user.restaurante_saas
        mesa = get_object_or_404(Mesa, numero=mesa_numero, restaurante=restaurante)
        pedidos = Pedido.objects.filter(mesa=mesa, status__in=['NOVO', 'CONFIRMADO', 'PRONTO', 'EM_TRANSITO', 'ENTREGUE', 'AGUARDANDO_CAIXA'])
        total_pago = sum(p.total for p in pedidos)
        
        if total_pago <= 0:
            return JsonResponse({'status': 'erro', 'msg': 'A mesa está vazia ou já foi paga.'})
            
        sdk = mercadopago.SDK(restaurante.mp_access_token) # 🚀 SaaS
        host_atual = request.get_host()
        
        if "localhost" in host_atual or "127.0.0.1" in host_atual:
            url_notificacao = "https://www.mercadopago.com.br" 
        else:
            url_notificacao = f"https://{host_atual}/api/webhook/mercadopago/"
        
        payment_data = {
            "transaction_amount": float(total_pago),
            "description": f"Pagamento Balcão Mesa {mesa.numero}",
            "payment_method_id": "pix",
            "external_reference": f"MESA_{mesa.id}", 
            "payer": {
                "email": "cliente@sandbox.com",
                "first_name": f"Mesa {mesa.numero}"
            },
            "notification_url": url_notificacao
        }
        
        result = sdk.payment().create(payment_data)
        payment = result.get("response", {})
        
        if "point_of_interaction" in payment:
            transaction_data = payment["point_of_interaction"]["transaction_data"]
            return JsonResponse({
                'status': 'sucesso',
                'qr_base64': transaction_data.get("qr_code_base64", ""),
                'qr_copia_cola': transaction_data.get("qr_code", "")
            })
        else:
            print("❌ ERRO DO MERCADO PAGO:", payment)
            msg_erro = payment.get('message', 'Erro interno do banco.')
            return JsonResponse({'status': 'erro', 'msg': f'Recusado: {msg_erro}'})
            
    except Exception as e:
        return JsonResponse({'status': 'erro', 'msg': str(e)})

@csrf_exempt
@transaction.atomic
@login_required(login_url='/accounts/login/')
def api_receber_mesa(request, mesa_numero):
    if request.method == 'POST':
        try:
            restaurante = request.user.restaurante_saas
            dados = json.loads(request.body)
            forma_pgto = dados.get('forma_pagamento', 'DINHEIRO')
            
            mesa = get_object_or_404(Mesa.objects.select_for_update(), numero=mesa_numero, restaurante=restaurante)
            pedidos = Pedido.objects.filter(mesa=mesa, status__in=['NOVO', 'CONFIRMADO', 'PRONTO', 'EM_TRANSITO', 'ENTREGUE', 'AGUARDANDO_CAIXA']).select_for_update()
            
            if not pedidos.exists():
                if not mesa.ocupada:
                    return JsonResponse({'status': 'sucesso'}) 
                return JsonResponse({'status': 'erro', 'msg': 'Não há pedidos aguardando nesta mesa.'})
            
            total_pago = sum(p.total for p in pedidos)
            
            caixa_aberto = Caixa.objects.filter(status='ABERTO', restaurante=restaurante).last()
            if caixa_aberto:
                MovimentacaoCaixa.objects.create(
                    caixa=caixa_aberto, tipo='ENTRADA',
                    descricao=f'Pagamento Balcão (Mesa {mesa.numero})',
                    valor=total_pago, forma_pagamento=forma_pgto
                )
            
            pedidos.update(status='FINALIZADO', forma_pagamento=forma_pgto)
            mesa.ocupada = False
            mesa.save()
            
            return JsonResponse({'status': 'sucesso'})
        except Exception as e:
            return JsonResponse({'status': 'erro', 'msg': str(e)}, status=500)
            
    return JsonResponse({'status': 'erro'}, status=400)
    
@csrf_exempt
def api_status_pix_mesa(request, mesa_numero):
    # 🚀 SaaS: A API de verificação rápida do PIX pode ser chamada pelo frontend, vamos buscar pelo ID global da mesa ou assumir a primeira
    try:
        mesa = Mesa.objects.get(id=mesa_numero) # Usa o ID primário do banco para evitar conflitos de "Mesa 1"
        pedidos = Pedido.objects.filter(
            mesa=mesa, 
            status__in=['NOVO', 'CONFIRMADO', 'PRONTO', 'EM_TRANSITO', 'ENTREGUE', 'AGUARDANDO_CAIXA']
        )
        return JsonResponse({'ocupada': pedidos.exists()})
    except Exception:
        return JsonResponse({'ocupada': False})
    
# 🚀 SaaS: Esta API agora recebe o slug na URL para saber os bairros de qual loja mostrar
def api_listar_bairros(request, slug):
    restaurante = get_object_or_404(Restaurante, slug=slug)
    bairros = list(Bairro.objects.filter(restaurante=restaurante, ativo=True).values('id', 'nome', 'taxa'))
    return JsonResponse({'bairros': bairros})

@login_required(login_url='/accounts/login/')
def api_verificar_alertas(request):
    try:
        restaurante = request.user.restaurante_saas
        qtd_novos = Pedido.objects.filter(restaurante=restaurante, status='NOVO').count()
        qtd_mesas = Pedido.objects.filter(restaurante=restaurante, origem='MESA', status__in=['AGUARDANDO_PAGAMENTO', 'NOVO']).count()
        
        return JsonResponse({
            'novos': qtd_novos,
            'mesas': qtd_mesas,
            'total_alertas': qtd_novos + qtd_mesas
        })
    except Exception:
        return JsonResponse({'total_alertas': 0})

def login_motoboy(request):
    if request.method == 'POST':
        entregador_id = request.POST.get('entregador_id')
        pin = request.POST.get('pin')
        
        try:
            entregador = Entregador.objects.get(id=entregador_id, pin=pin, ativo=True)
            request.session['entregador_id'] = entregador.id
            request.session['entregador_nome'] = entregador.nome
            request.session['restaurante_id'] = entregador.restaurante.id # 🚀 SaaS: Salva a loja do motoboy
            return redirect('painel_motoboy')
        except Entregador.DoesNotExist:
            messages.error(request, '❌ PIN incorreto! Tente novamente.')
            
    entregadores = Entregador.objects.filter(ativo=True)
    return render(request, 'core/login_motoboy.html', {'entregadores': entregadores})

def logout_motoboy(request):
    if 'entregador_id' in request.session:
        del request.session['entregador_id']
        del request.session['entregador_nome']
        if 'restaurante_id' in request.session:
            del request.session['restaurante_id']
    return redirect('login_motoboy')

def painel_motoboy(request):
    entregador_id = request.session.get('entregador_id')
    restaurante_id = request.session.get('restaurante_id')
    
    if not entregador_id or not restaurante_id:
        return redirect('login_motoboy')
        
    entregador = get_object_or_404(Entregador, id=entregador_id)
    hoje = timezone.localtime().date()
    
    # 1. CARTEIRA DE HOJE
    entregas_hoje = Pedido.objects.filter(entregador=entregador, status='ENTREGUE', atualizado_em__date=hoje)
    qtd_entregas = entregas_hoje.count()
    valor_ganho_hoje = entregas_hoje.aggregate(Sum('taxa_entrega'))['taxa_entrega__sum'] or 0.00
    
    # 2. EXTRATO (Histórico dos últimos 7 dias)
    historico = Pedido.objects.filter(
        entregador=entregador,
        status='ENTREGUE',
        atualizado_em__date__lt=hoje
    ).annotate(
        data_entrega=TruncDate('atualizado_em')
    ).values('data_entrega').annotate(
        qtd=Count('id'),
        total=Sum('taxa_entrega')
    ).order_by('-data_entrega')[:7]
    
    # 3. O RADAR BLINDADO (Apenas da loja deste motoboy) 🚀
    pedidos_livres = Pedido.objects.filter(
        restaurante_id=restaurante_id,
        tipo_entrega='ENTREGA',
        status__in=['PRONTO', 'EM_TRANSITO'],  # 👈 A MÁGICA AQUI: Só aparece quando a cozinha apertar em "Marcar Pronto"
        entregador__isnull=True
    ).order_by('criado_em')

    # 4. A BAGAGEIRA (O que ele já pegou e está levando)
    pedidos_pendentes = Pedido.objects.filter(
        entregador=entregador,
        status='EM_TRANSITO'
    ).order_by('criado_em') 
    
    context = {
        'entregador': entregador,
        'pedidos_livres': pedidos_livres,
        'pedidos_pendentes': pedidos_pendentes,
        'qtd_entregas': qtd_entregas,
        'valor_ganho_hoje': valor_ganho_hoje,
        'historico': historico,
    }
    return render(request, 'core/painel_motoboy.html', context)

@csrf_exempt
def api_finalizar_entrega(request, pedido_id):
    if request.method == 'POST':
        entregador_id = request.session.get('entregador_id')
        if not entregador_id:
            return JsonResponse({'status': 'erro', 'msg': 'Acesso negado. Faça login novamente.'})

        try:
            pedido = Pedido.objects.get(id=pedido_id, entregador_id=entregador_id)
            pedido.status = 'ENTREGUE'
            pedido.save()
            return JsonResponse({'status': 'sucesso', 'msg': 'Entrega finalizada com sucesso!'})
        except Pedido.DoesNotExist:
            return JsonResponse({'status': 'erro', 'msg': 'Pedido não encontrado ou já finalizado.'})
            
    return JsonResponse({'status': 'erro', 'msg': 'Método inválido.'})


@csrf_exempt
def api_aceitar_corrida(request, pedido_id):
    if request.method == 'POST':
        entregador_id = request.session.get('entregador_id')
        if not entregador_id:
            return JsonResponse({'status': 'erro', 'msg': 'Acesso negado.'})

        try:
            with transaction.atomic():
                pedido = Pedido.objects.select_for_update().get(id=pedido_id)
                
                if pedido.entregador is not None:
                    return JsonResponse({'status': 'erro', 'msg': 'Ops! 🛵💨 Outro motoboy foi mais rápido e já pegou esta corrida!'})
                
                entregador = Entregador.objects.get(id=entregador_id)
                pedido.entregador = entregador
                pedido.status = 'EM_TRANSITO'
                pedido.save()

                if pedido.cliente_whatsapp and pedido.restaurante.ultramsg_instance:
                    host = request.get_host()
                    link = f"http://{host}/loja/{pedido.restaurante.slug}/rastreio/{pedido.id_pedido}/"
                    msg = f"🛵 *VRUUUM!* O motoboy {entregador.nome} acabou de pegar o seu pedido #{pedido.numero_diario:03d} e está a caminho, {pedido.cliente_nome}!\n\nAcompanhe-o no mapa ao vivo:\n📍 {link}"
                    disparar_whatsapp_async(pedido.cliente_whatsapp, msg, pedido.restaurante)
                
                return JsonResponse({'status': 'sucesso', 'msg': 'Corrida aceita! Vá buscar o lanche.'})
        except Pedido.DoesNotExist:
            return JsonResponse({'status': 'erro', 'msg': 'Pedido não encontrado.'})
            
    return JsonResponse({'status': 'erro', 'msg': 'Método inválido.'})

@csrf_exempt
def api_localizacao_motoboy(request, pedido_id):
    """ Devolve a posição GPS atual daquele pedido para a tela do Cliente """
    try:
        pedido = Pedido.objects.get(id_pedido=pedido_id)
        return JsonResponse({
            'status': 'ok',
            'lat': pedido.motoboy_lat,
            'lng': pedido.motoboy_lng
        })
    except Pedido.DoesNotExist:
        return JsonResponse({'status': 'erro'})
    
@login_required(login_url='/accounts/login/')
def configuracoes_loja(request):
    restaurante = request.user.restaurante_saas
    
    if request.method == 'POST':
        form = RestauranteForm(request.POST, request.FILES, instance=restaurante)
        if form.is_valid():
            form.save()
            messages.success(request, 'Configurações atualizadas com sucesso!')
            return redirect('configuracoes_loja')
        else:
            messages.error(request, 'Erro ao atualizar as configurações. Verifique os dados.')
    else:
        form = RestauranteForm(instance=restaurante)
        
    return render(request, 'core/configuracoes.html', {'form': form, 'restaurante': restaurante})


@login_required(login_url='/accounts/login/')
def minha_assinatura(request):
    restaurante = request.user.restaurante_saas
    
    # Calcula os dias restantes para o vencimento
    dias_restantes = 0
    if restaurante.vencimento_assinatura:
        hoje = timezone.localtime().date()
        dias_restantes = (restaurante.vencimento_assinatura - hoje).days
        
    context = {
        'restaurante': restaurante,
        'dias_restantes': dias_restantes,
    }
    return render(request, 'core/assinatura.html', context)

@login_required(login_url='/accounts/login/')
def api_gerar_pagamento_saas(request):
    """ Gera o Checkout Pro do Mercado Pago (PIX + Cartão de Crédito) para o SaaS """
    try:
        restaurante = request.user.restaurante_saas
        valor_plano = float(restaurante.valor_mensalidade)
        
        # ⚠️ SEU TOKEN DE PRODUÇÃO AQUI (Conta que vai receber o dinheiro)
        TOKEN_MASTER_SAAS = "APP_USR-6237062141884906-021814-a34559040cdd3c5c2c02badc909ec6d4-1242834927"
        sdk = mercadopago.SDK(TOKEN_MASTER_SAAS) 
        
        host_atual = request.get_host()
        
        # 🚀 CAMUFLAGEM TOTAL E CORREÇÃO DO NGROK
        if "localhost" in host_atual or "127.0.0.1" in host_atual:
            url_notificacao = "https://www.mercadopago.com.br"
            url_sucesso = "https://www.google.com" # Engana o banco para aprovar o link local
            url_falha = "https://www.google.com"   # Engana o banco para aprovar o link local
        else:
            # 🚀 AQUI ESTAVA O ERRO! Forçamos o 'https://' manualmente.
            # Como o Ngrok e os servidores reais usam HTTPS, o Mercado Pago vai aceitar de imediato!
            url_notificacao = f"https://{host_atual}/api/webhook/mercadopago/"
            url_sucesso = f"https://{host_atual}/painel/"
            url_falha = f"https://{host_atual}/painel/assinatura/"

        # Cria a "Preferência de Pagamento" (Permite Cartão, PIX, etc)
        preference_data = {
            "items": [
                {
                    "title": f"Plano Aliance Pro - {restaurante.nome}",
                    "quantity": 1,
                    "currency_id": "BRL",
                    "unit_price": valor_plano
                }
            ],
            "payer": {
                # 🚀 SEGREDO 2: Se o lojista não tiver e-mail no cadastro, passamos um genérico
                "email": request.user.email if request.user.email else "contato@aliancefood.com.br",
            },
            "external_reference": f"SAAS_{restaurante.id}", # O Webhook usa isto para saber quem pagou!
            "back_urls": {
                "success": url_sucesso,
                "failure": url_falha,
                "pending": url_falha
            },
            "auto_return": "approved", # Volta sozinho quando o banco aprova
            "notification_url": url_notificacao
        }
        
        result = sdk.preference().create(preference_data)
        
        if result.get("status") == 201:
            # Pega o link seguro do Mercado Pago
            link_checkout = result["response"]["init_point"]
            return JsonResponse({'status': 'sucesso', 'link': link_checkout})
        else:
            print("❌ ERRO MP PREFERENCE:", result)
            return JsonResponse({'status': 'erro', 'msg': 'Erro ao gerar link de pagamento.'})
            
    except Exception as e:
        return JsonResponse({'status': 'erro', 'msg': str(e)})
    
def manifest_pwa(request, slug):
    """ Gera o ficheiro de Aplicativo (PWA) dinâmico para cada loja do SaaS """
    restaurante = get_object_or_404(Restaurante, slug=slug)
    
    # Se a loja não tiver logo, usamos um genérico do sistema
    icon_url = restaurante.logo.url if restaurante.logo else '/static/img/icone-padrao.png'
    
    manifest = {
        "name": restaurante.nome,
        "short_name": restaurante.nome,
        "start_url": f"/loja/{restaurante.slug}/",
        "display": "standalone", # Isto esconde a barra do navegador, parecendo um App nativo!
        "background_color": "#ffffff",
        "theme_color": restaurante.cor_principal, # Puxa a cor exata da loja
        "icons": [
            {
                "src": icon_url,
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": icon_url,
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    }
    return JsonResponse(manifest)