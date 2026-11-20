# Roteiro do pitch · Sovereign Shift

**4 min 30 s · 5 slides · 2 pessoas.** A abre e fecha o pitch. B opera a demo e apresenta os resultados.

## Antes de entrar

Na raiz do repositório, preparem a demo local com o projeto instalado.

```bash
.venv/bin/sovereign-shift all --from-snapshot testdata/clickops_inventory.json --no-ai --out out/pitch
```

Abram o PowerPoint e deixem três janelas prontas. Abram `out/pitch/graph.html` no navegador, `out/pitch/terraform/main.tf` junto de `reference = "web-1"` e `out/pitch/report.md` junto de `pg_dump`. Ensaiem a troca de janelas. Se a demo falhar, usem a seta do slide 2 e descrevam as três entregas do slide 3.

## 0:00–0:35 · Slide 1 · A abre

Façam uma pausa a seguir à pergunta do slide.

«Imaginem que amanhã vos pedem para mudar uma loja da AWS para a Leaseweb. A infraestrutura foi montada na consola. Como descobrem o que têm de levar? O Sovereign Shift lê a conta com acesso só de leitura e prepara um plano de migração que a equipa pode rever.»

## 0:35–1:10 · Slide 2 · A apresenta a loja

Apontem do servidor para a base de dados e passem a palavra a B.

«Nesta loja fictícia, uma regra permite que o servidor web-1 chegue à base de dados orders pela porta 5432. É uma dependência inferida a partir da rede. A equipa confirma se a aplicação usa de facto essa ligação. Vamos seguir este exemplo até ao plano de migração.»

## 1:10–2:50 · Slide 3 · B faz a demo

| Tempo | O que mostrar | O que dizer |
|---|---|---|
| 1:10–1:40 | Abram o grafo e apontem para web-1 e orders. | «O grafo mostra a ligação inferida e ajuda-nos a perceber o que temos de confirmar com a equipa.» |
| 1:40–2:10 | Abram o Terraform e apontem para o recurso de web-1, o tipo e o disco. | «O mesmo servidor aparece no Terraform para a Leaseweb. Estes atributos vêm de regras e templates.» |
| 2:10–2:50 | Abram o relatório no passo pg_dump e apontem para os campos a preencher. Voltem ao slide 4. | «O runbook traz um passo de exportação PostgreSQL. O operador fornece o host e a base de dados e pode rever o comando antes de o executar.» |

## 2:50–3:55 · Slide 4 · B apresenta a validação

Façam uma pausa ao passar da loja fictícia para a conta real. Apontem para os três números.

«Também corremos o workflow duas vezes sobre uma conta real na região AWS de Estocolmo. O inventário encontrou 20 recursos. As regras produziram 11 mapeamentos automáticos. Sete recursos ficaram com trabalho complementar e dois exigem tratamento manual. O Terraform gerado passou a validação. Falta testar o aprovisionamento, o restauro e o serviço no destino.»

[Primeira leitura real](https://github.com/FranciscoJanuarioSilva/sovereign-shift/actions/runs/44731393006) · [Repetição](https://github.com/FranciscoJanuarioSilva/sovereign-shift/actions/runs/44731585599)

## 3:55–4:30 · Slide 5 · A fecha

Olhem para o público e terminem com o convite.

«Para o piloto, queremos escolher uma aplicação pequena, confirmar as dependências com a equipa e ensaiar o restauro num destino isolado. Que aplicação da vossa equipa escolheriam?»

## Perguntas do júri

- **Onde entra a IA?** É opcional e pode sugerir alternativas ou personalizar o runbook. Os comandos vêm de templates e passam por validação. A demo local corre com a IA desligada.
- **Quanto se poupa?** As três linhas com preços na loja fictícia somam 155,95 €/mês na AWS e 113,49 €/mês na Leaseweb. Para um orçamento é preciso completar os preços em falta.
- **Podemos repetir?** Repetimos a leitura e a geração sobre a conta real. A repetição de um aprovisionamento ou de uma transferência de dados precisa de um ensaio próprio.
