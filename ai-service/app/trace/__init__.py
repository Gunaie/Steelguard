"""阶段4: 缺陷溯源(相似检索)模块

- embedder: ResNet50(ImageNet 预训练) 抽 2048 维裁剪图特征, L2 归一化
- milvus_client: defect_cases collection(FLAT + COSINE, 小库精确检索)
- store: 裁剪图传 MinIO + defect_case 落 MySQL + 搜索结果回查拼装
- router: /trace/index(内部入库) /trace/search(以图搜图)
"""
