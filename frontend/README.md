# 前端演示

先启动后端：

```powershell
$env:PYTHONPATH='src'
python -m standard_knowledge_service_v2.main --serve
```

然后直接双击 `index.html`，或在本目录执行 `python -m http.server 5500 -d frontend`，浏览器打开 <http://127.0.0.1:5500>。

页面支持选择五个场景、输入自然语言问题、填写设备参数，并查看 DeepSeek 分解、场景模型、标准匹配和候选指令。演示模式始终禁止真实下发。
