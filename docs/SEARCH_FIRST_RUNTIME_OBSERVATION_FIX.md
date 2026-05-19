# v2.9.24 Search-first and runtime-observation contract fix

## 修正点

- 外部情報系の実行方式は `web_search` を第一候補にし、十分な evidence が得られた場合は API discovery / API call に進まない。
- API は evidence 不足時の escalation としてのみ実行する。
- 上流 intent がすでに正規化済みパラメータを持つ場合、同じパラメータ取得だけを行う冗長 step は `skip_execution` として扱う。
- runtime observation 系の intent は外部 web / API に流れないように、temporal marker を含む contract 判定を強化した。
- `skip_execution` は失敗や block として扱わず、後続 step の実行を妨げない。

## タイムアウト方針

- 全体 execution timeout: 180 秒以上を想定
- web discovery / web search / extraction / API discovery / API call を stage 単位で制御
- 一つの method が失敗または timeout しても、contract で許可された fallback のみ継続

## 注意

この修正は業務固有 API 名やドメイン固有サイト名を持たない。判断は intent contract、normalized parameters、execution method policy、source level に基づく。
