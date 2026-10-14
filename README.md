# Structure Blast — biblioteca comunitária

Envie um STEP, receba um GLB pronto para o jogo. A conversão roda no GitHub Actions e não usa o Render.

## Publicar este pacote no GitHub

1. Crie um repositório **público** com o nome `structure-blast-modelos` e branch principal `main`.
2. Extraia este ZIP e envie seu **conteúdo** para a raiz do repositório. Preserve a pasta `.github/workflows/`, onde fica a automação. Não envie apenas o ZIP.
3. Na aba Actions, habilite os workflows se o GitHub solicitar. Abra **Converter STEP para GLB → Run workflow** para o primeiro teste.
4. Ao terminar, o robô faz um commit com os GLBs em `modelos/` e com `catalogo.json` atualizado.

O workflow solicita `contents: write` para gravar somente neste repositório. Se a conta/organização proibir escrita por Actions, ajuste a política em **Settings → Actions → General**. Proteção de branch pode exigir publicar as saídas por pull request; o workflow não contorna essas regras.

Não é necessário token pessoal no código. O workflow usa o GITHUB_TOKEN temporário fornecido pelo próprio GitHub.

## Como contribuir

- Com permissão de escrita: abra `originais/`, use Add file → Upload files e envie `.step` ou `.stp` para `main`.
- Sem permissão: crie um fork e envie um pull request; a conversão acontece **depois que o mantenedor aceitar**.
- Opcionalmente, envie um JSON com o mesmo nome: `galpao.step` + `galpao.json`.

Exemplo de metadados:

```json
{
  "name": "Galpão do Raffael",
  "author": "Raffael",
  "description": "Estrutura metálica com as peças separadas."
}
```

Só envie modelos que você tem autorização para disponibilizar publicamente.

## Automação

- Aceita STEP/STP, inclusive em subpastas de `originais/`.
- Mantém a hierarquia e cores que o importador consegue ler; não funde a montagem inteira.
- Une faces de uma mesma peça quando possível para evitar centenas de malhas por peça no jogo.
- Gera GLB independente de arquivos externos, com orientação Y para cima e escala em metros.
- Cada saída recebe nome estável com um identificador derivado do caminho. Arquivos homônimos em pastas diferentes não se sobrescrevem.
- Compara hashes e converte apenas arquivos novos ou alterados. Alterar o conversor/configurações também invalida o cache.
- Alterar somente nome/autor/descrição atualiza o catálogo sem repetir a conversão.
- Remover um STEP remove a saída correspondente e a entrada do catálogo na próxima execução.
- Se um arquivo falhar, a publicação é interrompida e o catálogo anterior fica disponível.
- Limite inicial: 20 MiB de entrada e saída por modelo, 500 instâncias de malha, 300 mil triângulos e 180 segundos de conversão por arquivo. Ajuste em `config.json`.
- Modelos grandes precisam ser simplificados. A conversão para GLB não cria fraturas e não garante um arquivo pequeno.

O job tem limite de 30 minutos. Se houver muitas conversões de uma vez, envie em lotes menores. Se alguém alterar `main` durante a conversão, o push pode ser rejeitado sem sobrescrever nada: execute Run workflow novamente.

## Como o jogo acessará

Após publicar, substitua `SEU_USUARIO` abaixo pelo dono do repositório:

```text
https://raw.githubusercontent.com/SEU_USUARIO/structure-blast-modelos/main/catalogo.json
```

O catálogo contém uma lista `models`. O campo `file` é relativo à raiz do repositório, por exemplo `modelos/portico-exemplo-84bf2f67bc.glb`. Cada entrada inclui nome, autor, tamanho, número de malhas/triângulos e SHA-256.

O arquivo `biblioteca-client.js` traz funções para consultar o catálogo e baixar/verificar um GLB apenas quando selecionado. É um módulo de integração, **não uma modificação automática do jogo**. Depois de publicar o repositório, ainda é necessário conectar esse módulo à interface e aos eventos multiplayer do jogo.

Uma URL raw de `main` pode ficar temporariamente em cache. O cliente verifica o hash do GLB: se catálogo e arquivo ainda estiverem em versões diferentes, avisa para tentar novamente. Para versões imutáveis, substitua `main` pelo SHA de um commit.

Não é necessário clonar toda a biblioteca no Render. O navegador pode buscar o catálogo e o arquivo escolhido diretamente pela URL pública. GitHub não deve ser tratado como armazenamento/CDN ilimitado; para biblioteca grande ou tráfego alto, publique os GLBs em armazenamento de objetos apropriado.

## Rodar no seu PC (opcional)

Recomendado: Python 3.11, em ambiente virtual.

```bash
python -m pip install -r requirements.txt
python scripts/converter.py
```

A automação foi escrita para Ubuntu 24.04 / Python 3.11. Conversão local foi testada com CadQuery 2.7.0. Não foi executada na sua conta do GitHub nesta entrega.

## Exemplo incluído

`originais/portico-exemplo.step` tem duas colunas e uma viga com duas cores. Seu GLB já foi gerado e incluído para testar a biblioteca imediatamente. Você pode excluir os dois arquivos do exemplo em `originais/`; a automação removerá a saída gerada.

Arquivos principais:

- `.github/workflows/converter.yml`: gatilhos e publicação automática.
- `scripts/converter.py`: importação, tesselação, validação e catálogo incremental.
- `config.json`: qualidade e limites.
- `originais/`: contribuições STEP/STP e metadados opcionais.
- `modelos/`: GLBs gerados; não edite manualmente.
- `catalogo.json`: catálogo gerado.
- `biblioteca-client.js`: módulo para integrar ao jogo.
- `TESTES.md`: verificação local e limitações.
