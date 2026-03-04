from django import forms
from .models import Produto, Categoria, Adicional, Restaurante # Certifique-se de importar Categoria e Adicional

class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = ['nome', 'descricao', 'preco', 'categoria', 'imagem', 'ativo', 'adicionais_disponiveis', 'sabores']
        
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Pizza Meio a Meio / Combo Família'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Detalhes dos ingredientes ou regras...'}),
            'preco': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'imagem': forms.FileInput(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'adicionais_disponiveis': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 4}), # Size 4 para caber mais itens visíveis
            'sabores': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Calabresa, Marguerita, Frango (separe por vírgula)'}),
        }

    # 🚀 BLINDAGEM SAAS ALIANCEFOOD
    def __init__(self, *args, **kwargs):
        # 1. Pega a loja (inquilino) que a View enviou
        restaurante = kwargs.pop('restaurante', None)
        
        super(ProdutoForm, self).__init__(*args, **kwargs)
        
        # 2. Se existe um restaurante, filtramos tudo o que tem relação de pertencimento!
        if restaurante:
            # Blindagem 1: Categorias exclusivas da loja
            if 'categoria' in self.fields:
                self.fields['categoria'].queryset = Categoria.objects.filter(restaurante=restaurante)
            
            # Blindagem 2: Adicionais exclusivos da loja (Bordas, Extras, Bebidas)
            if 'adicionais_disponiveis' in self.fields:
                self.fields['adicionais_disponiveis'].queryset = Adicional.objects.filter(restaurante=restaurante)



class RestauranteForm(forms.ModelForm):
    class Meta:
        model = Restaurante
        fields = ['nome', 'telefone', 'endereco', 'cep', 'tempo_entrega', 'mensagem_fechado', 'aberta']
        
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control form-control-lg', 'placeholder': 'Nome da Loja'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control form-control-lg', 'placeholder': 'WhatsApp com DDD (Ex: 21999999999)'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Rua, Número, Bairro...'}),
            'cep': forms.TextInput(attrs={'class': 'form-control form-control-lg', 'placeholder': '00000-000'}),
            'tempo_entrega': forms.TextInput(attrs={'class': 'form-control form-control-lg', 'placeholder': 'Ex: 30-45 min'}),
            'mensagem_fechado': forms.TextInput(attrs={'class': 'form-control form-control-lg'}),
            # LIGADO AO CAMPO 'aberta' DA BASE DE DADOS
            'aberta': forms.CheckboxInput(attrs={'class': 'form-check-input', 'style': 'width: 2.5rem; height: 1.25rem; cursor: pointer;'}),
        }