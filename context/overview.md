> Primeira análise, antes da pesquisa à API da Leaseweb. As security groups passaram para a API (finalize), não nftables. Ver `PLAN.md`.

A ideia é boa e encaixa bem no tema. Há uma descoberta que muda o MVP: o provider Terraform da Leaseweb não tem recursos para security groups/firewall, redes privadas, Kubernetes nem object storage. Por isso, "EC2 + security groups + S3", a prioridade nº1 do plano, não se gera diretamente. Atualizei o [context/idea.md](context/idea.md) com tudo o que está abaixo, incluindo a correção do nome "soverein" para "sovereign".

## Enquadramento com o tema
- **Cobre os três temas do júri:** IA para infraestrutura (a tradução feita pelo LLM), migração para uma alternativa soberana e segurança (os alertas do scan).
- **Aplicabilidade:** o problema veio de um funcionário da Leaseweb e há dois juízes da Leaseweb. A parte de negócio ("cada relatório é um lead qualificado") fala diretamente com eles.

## É inovador?
- **Passar de ClickOps para código já existe:** aws2tf, Former2, Firefly/aiac, StackGuardian, `terraform plan -generate-config-out`.
- **Mas todos geram Terraform para o próprio AWS.** Não encontrei nenhuma ferramenta que traduza AWS para outro provider, muito menos para a Leaseweb. Isto dá uma frase forte para o pitch: *"As ferramentas que existem transformam o teu ClickOps em Terraform da AWS, e isso prende-te à AWS. Nós transformamo-lo em Terraform da Leaseweb."*

## O que o provider da Leaseweb suporta
A versão é a v1.32.1, de outubro de 2026, e já não é beta.

| AWS | Leaseweb |
|---|---|
| EC2 | `leaseweb_public_cloud_instance` ✅ |
| ALB/NLB | `load_balancer` + `listener` + `target_group` ✅ |
| Route 53 | `dns_resource_record_set` ✅ |
| Security group | ❌ não existe. O LLM gera regras nftables dentro do cloud-init (`user_data`) |
| S3 | ❌ foi adicionado na 1.32.0 e retirado na 1.32.1. Geramos um script `rclone` |
| RDS e o resto | trabalho manual, com uma alternativa open-source sugerida pelo LLM |

Isto ajuda na nota de complexidade técnica. Escolher o tamanho da instância uma regra simples resolve, e o júri pode achar o LLM decorativo. Traduzir security groups para nftables, mapear AMIs, propor alternativas e um ciclo em que o LLM corrige o próprio output com base nos erros do `terraform validate` são trabalho que só a IA faz.

Três armadilhas a ter em conta:
- **Regiões:** a Leaseweb usa nomes iguais aos da AWS (`eu-west-3`) mas são outros sítios. É preciso mapear, nunca copiar.
- **`ssh_key` e `user_data`:** não se podem usar os dois ao mesmo tempo, por isso a chave SSH vai dentro do cloud-init.
- **Exemplo da documentação:** usa `private_network`, mas no schema o atributo é `has_private_network`.

## A vossa pergunta: usar uma ferramenta ou fazer nós?
Recomendo fazer nós o scanner em boto3 e não usar nenhuma destas como dependência:
- **Não resolvem o nosso problema:** geram HCL da AWS, e a parte difícil, que é a tradução, teria de ser feita na mesma.
- **Terraformer:** está arquivado desde março de 2026.
- **terracognita:** está fixo num provider AWS antigo.
- **Former2:** só funciona no browser.
- **aws2tf:** precisa de Terraform 1.12, AWS CLI v2 e jq, e não produz um inventário em JSON.
- **O scanner é pouco trabalho:** para 6 a 8 tipos de recurso são poucas centenas de linhas, e controlamos as `relations` do grafo.
- **Extra opcional:** a API de resource scan do CloudFormation (`start_resource_scan`, existe no boto3) conta *todos* os recursos da conta. Isso permite ao relatório dizer "encontrámos 143 recursos, 38 migram automaticamente". Só devolve tipos e IDs, sem atributos, e demora alguns minutos, por isso corre-se antes da demo.

## Riscos para levar ao organizador
1. **Pedir um token da API da Leaseweb.** Com ele, a demo acaba num `terraform apply` real. Isto é o mais importante. Também não sei se `terraform plan` funciona com um token falso: testem nos primeiros 15 minutos.
2. **Ver o hardware da VM.** Sem GPU, o Ollama demora 10 a 30 segundos por chamada. Guardem as respostas em cache e tenham uma API como alternativa (a Mistral é europeia e encaixa na história).
3. **Criar já a conta AWS de demo, à mão na consola:** 2 EC2, 1 ALB, security groups com uma regra má (22 ou 5432 abertos ao mundo), um bucket S3 público e um volume EBS sem encriptação.
4. **Os dados não migram:** discos, objetos do S3 e bases de dados ficam de fora do Terraform. O relatório deve trazer um plano de migração de dados (rsync, rclone, pg_dump). Digam-no no pitch antes de um juiz perguntar.
5. **O tempo é curto:** o feature freeze é às 15:00, o que dá cerca de 5 horas úteis. A prioridade nº1 passa a ser EC2 + security groups (via nftables) + ALB.

Fontes: [provider da Leaseweb](https://github.com/leaseweb/terraform-provider-leaseweb), [aws2tf](https://github.com/aws-samples/aws2tf), [Terraformer](https://github.com/GoogleCloudPlatform/terraformer), [Former2](https://github.com/iann0036/former2), [terracognita](https://github.com/cycloidio/terracognita), [API StartResourceScan](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_StartResourceScan.html), [StackGuardian](https://www.stackguardian.io/solution/use-case/infra2code), [Firefly/aiac na CNCF](https://www.cncf.io/online-programs/cloud-native-live-iac-migration-using-ai-from-cloudformation-to-terraform-in-seconds/), [Leaseweb Public Cloud](https://www.leaseweb.com/cloud/public-cloud), [blog Leaseweb sobre Terraform](https://blog.leaseweb.com/?p=8558).