# Verificação local

Testado com conversão real usando CadQuery 2.7.0 e OCCT, não apenas com arquivos simulados.

- Pórtico STEP convertido em GLB com 3 instâncias de malha, 36 triângulos e 2 materiais.
- Faces de cada peça unidas em um primitive por peça no exemplo, preservando as 3 peças separadas.
- Escala explícita de milímetros para metros: largura de 3200 mm resulta em 3,2 m.
- Segunda execução reutiliza a saída; nenhum GLB regravado.
- Alteração de metadados atualiza nome sem alterar o hash do GLB.
- STEP inválido interrompe publicação e preserva catálogo anterior byte a byte.
- Dois STEP com mesmo nome em pastas diferentes geram IDs/arquivos distintos.
- Remoção das entradas remove as saídas correspondentes e esvazia o catálogo.
- Cliente JavaScript consultou catálogo e verificou GLB; rejeitou hash incorreto em teste com respostas HTTP simuladas.

Para reproduzir o teste do pipeline, instale requirements.txt e execute:

```bash
python -m unittest discover -s tests -v
```

Ainda não testado: execução na conta GitHub do usuário, permissões de push dessa conta, arquivos STEP reais do usuário, integração multiplayer com o jogo e download através do domínio raw do repositório futuro.

O teste do pórtico não garante que todo STEP preserve todas as cores/hierarquias. STEP contendo uma peça única não será automaticamente dividido em componentes independentes. A qualidade depende da estrutura do arquivo original.
