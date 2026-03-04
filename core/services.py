import threading
import requests

def disparar_whatsapp_async(numero, mensagem):
    """
    Roda em segundo plano (Thread) para não travar a tela do cliente.
    Agora com a integração REAL da UltraMsg!
    """
    def tarefa_em_background():
        print(f"\n⏳ [BACKGROUND JOB] Preparando envio de WhatsApp para {numero}...")
        
        if not numero or len(str(numero)) < 8:
            print("❌ [BACKGROUND JOB] Número inválido ou vazio. Cancelando envio.")
            return

        # ========================================================
        # ⚠️ COLE SEUS CÓDIGOS DA ULTRAMSG AQUI EMBAIXO
        # ========================================================
        INSTANCE_ID = "instance162483"
        TOKEN = "872kuk55ci68k88b"
        
        # 1. Limpa o número (tira traços, parênteses e espaços que o cliente digitar)
        numero_limpo = ''.join(filter(str.isdigit, str(numero)))
        
        # 2. Garante que tem o código do Brasil (55) no começo
        if not numero_limpo.startswith('55'):
            numero_limpo = '55' + numero_limpo
            
        # 3. Prepara o "pacote" para enviar para a UltraMsg
        url = f"https://api.ultramsg.com/{INSTANCE_ID}/messages/chat"
        payload = {
            "token": TOKEN,
            "to": numero_limpo,
            "body": mensagem
        }
        headers = {'content-type': 'application/x-www-form-urlencoded'}
        
        # 4. Tenta fazer o disparo real!
        try:
            response = requests.post(url, data=payload, headers=headers)
            print(f"✅ [BACKGROUND JOB] Mensagem entregue para {numero_limpo}!")
            print(f"📡 Resposta da API: {response.text}\n")
        except Exception as e:
            print(f"❌ [BACKGROUND JOB] Erro grave ao enviar para {numero_limpo}: {e}\n")

    # Inicia o processo em segundo plano
    thread = threading.Thread(target=tarefa_em_background)
    thread.start()