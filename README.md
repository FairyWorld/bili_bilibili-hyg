# bilibili-hyg
bilibili 会员购 抢票脚本

本脚本不同于其他脚本，直接调用api，存在一定风控风险，脚本提供者不为您的行为负责。

本脚本仅供学习交流，请在24小时内停止运行并删除本脚本。

本脚本若需自动化快速启动（免去参数配置）请参考[Wiki](https://github.com/ZianTT/bilibili-hyg/wiki/关于快速启动（自动化启动）配置的说明)

本脚本常见错误情况请参考[Wiki](https://github.com/ZianTT/bilibili-hyg/wiki/%E5%85%B3%E4%BA%8E%E9%83%A8%E5%88%86%E9%94%99%E8%AF%AF%E6%83%85%E5%86%B5%E7%9A%84%E8%A7%A3%E9%87%8A)

显示抢到了却没有，请参考 [#2](https://github.com/ZianTT/bilibili-hyg/issues/2)

PS：这个脚本也是支持抢回流票的，~~但是最近的BW和BML似乎是不放回流票了~~，又放了，各位看着抢。至于刷新间隔，绝对是很小的，不会有什么错过的情况，只有检测到但是被秒掉的情况（jio本也太多了扒）

另外针对GeeTest验证码我也没有什么好的解决方案，如果有xd有GeeTest的能用的现成轮子欢迎推荐给我吖

## 依赖安装

首先，克隆本仓库或者下载origin.py文件。

本脚本基于Python编写，需要Python3来运行。运行前需要`requests`库支持。您可以使用以下代码安装

```shell
pip3 install requests
```

之后可以直接运行

```shell
python3 origin.py
```

## 使用教程

登录 show.bilibili.com ，F12打开浏览器开发者工具，选择Network(网络)选项卡，~~选一个看着像的~~点开，在标头(Header)选项卡中找到请求标头中的Cookie，整行复制并按提示输入。

项目id则为活动详情页url中id的参数，一般为7开头的数字，如BW2023为73710

接下来根据提示选择场次，购票人（购买单场次多张票可多选购票人，格式：0,1）

触发风控时，请访问给出的链接人工验证，完成验证后按下回车继续

若抢票成功，可在任何一端访问订单页支付，防止放票

如有侵权请联系删除
