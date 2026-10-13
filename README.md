# FarmTech Solutions · Visão computacional com YOLO

**FIAP · Inteligência Artificial · Fase 6**
Dupla: Guilherme Ávila (RM XXXXX) e Kainan (RM XXXXX)

A FarmTech Solutions expandiu seus serviços de IA para saúde animal e segurança de propriedades rurais. Neste projeto, treinamos um detector de objetos que localiza e diferencia **vacas** e **cachorros** em fotos, e mostramos ao cliente como o sistema se comporta com imagens que ele nunca viu.

## Entregas

| Entrega | O que é | Onde está |
|---|---|---|
| 1 | YOLOv5 customizado para vaca e cachorro, com treinos de 30 e 60 épocas comparados | [Notebook da Entrega 1](notebooks/NomeCompleto_rmXXXXX_pbl_fase6.ipynb) · [Abrir no Colab](https://colab.research.google.com/github/Avila237/guilherme-kainan-fiap-fase6/blob/main/notebooks/NomeCompleto_rmXXXXX_pbl_fase6.ipynb) |
| 2 | Comparação com o YOLO pré-treinado e com uma CNN treinada do zero | Em desenvolvimento |

**Vídeo de demonstração:** em breve.

O passo a passo completo, os resultados e as conclusões estão no notebook. Este README só apresenta o projeto e organiza os arquivos.

## Como executar

Abra o notebook pelo link **Abrir no Colab** acima, selecione um ambiente com GPU (*Ambiente de execução → Alterar o tipo de ambiente de execução → GPU T4*) e execute todas as células. O notebook baixa o dataset deste repositório e uma versão fixa do YOLOv5. Não é preciso acesso ao nosso Google Drive.

### Alternativa: Windows com GPU NVIDIA

Para treinar num PC próprio, abra o PowerShell e rode, nesta ordem:

```powershell
irm https://raw.githubusercontent.com/Avila237/guilherme-kainan-fiap-fase6/main/scripts/windows/setup_windows.ps1 -OutFile setup_windows.ps1
powershell -ExecutionPolicy Bypass -File setup_windows.ps1
powershell -ExecutionPolicy Bypass -File "$HOME\fiap-fase6\scripts\windows\run_windows.ps1"
```

O `setup_windows.ps1` instala o que faltar (Git, Python 3.12, PyTorch com CUDA 12.6, YOLOv5 e Jupyter) em `%USERPROFILE%\fiap-fase6` e confirma que a GPU foi reconhecida. O `run_windows.ps1` executa o notebook inteiro e salva a cópia com as saídas em `notebooks\<nome>_executado.ipynb`. O notebook detecta sozinho se há GPU NVIDIA, GPU Apple (MPS) ou só CPU.

## Estrutura

```
├── dataset/
│   ├── data.yaml          # configuração do dataset para o YOLOv5 (cow = 0, dog = 1)
│   ├── fontes.csv         # autor, licença e link de origem de cada imagem
│   ├── approved.txt       # seleção final das imagens após a curadoria
│   ├── images/            # 80 imagens: train (64), val (8), test (8)
│   └── labels/            # um .txt por imagem, no formato YOLO
├── notebooks/             # notebooks das entregas
└── scripts/
    ├── collect_images.py  # coleta das imagens e montagem do dataset (com testes)
    └── windows/           # instalação e execução do notebook num PC Windows com GPU NVIDIA
```

## Dataset e licenças

As 80 imagens são fotos do Flickr obtidas pela API do [Openverse](https://openverse.org), todas com licenças que permitem redistribuição:

| Licença | Imagens |
|---|---|
| [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/) | 41 |
| [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/) | 34 |
| [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | 3 |
| [Public Domain Mark 1.0](https://creativecommons.org/publicdomain/mark/1.0/) | 2 |

A atribuição de cada imagem (título, autor, licença e link da foto original) está em [`dataset/fontes.csv`](dataset/fontes.csv). As imagens CC BY-SA continuam sob a mesma licença CC BY-SA 2.0. As imagens não foram modificadas; os rótulos (`dataset/labels/`) são trabalho nosso.

Nenhuma imagem faz parte do dataset COCO: o script de coleta descarta qualquer foto cujo ID do Flickr conste no COCO train2017 ou val2017, para que a comparação com o YOLO pré-treinado na Entrega 2 seja justa.
