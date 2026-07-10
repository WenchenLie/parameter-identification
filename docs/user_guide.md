# Hysteresis Parameter Identification (HPI) 用户文档

## 1. 程序用途

Hysteresis Parameter Identification (HPI) 用于根据试验滞回曲线识别 OpenSees 单轴材料模型参数。程序通过优化算法不断生成材料参数，调用 OpenSees Python 模块计算模拟滞回响应，并以 RMSE 作为目标函数评价模拟曲线与试验曲线的差异。

## 2. 启动程序

源码方式启动：

```powershell
python .\main.py
```

后续打包后，也可以直接双击或运行可执行文件启动：

```powershell
HPI-v<版本号>.exe
```

默认使用内置 OpenSees 模块：

```text
resources\opensees\opensees.pyd
```

注意：当前内置 `.pyd` 支持的 Python 版本为 **Python 3.14**。如需使用其他 `opensees.pyd`，请确保它与当前 Python 版本匹配，然后勾选 `Custom opensees.pyd` 并选择文件。

## 3. 参数定义页

### 3.1 试验数据

点击 `Browse` 选择试验数据文件。数据文件至少包含两列：

- 第 1 列：位移
- 第 2 列：力

点击 `Load / Refresh Curve` 后，程序会读取曲线并显示在左下方图中。

### 3.2 骨架点

`Skeleton method` 提供两种骨架点识别方式：

- `Max displacement`：按反向点最大位移确定骨架点
- `Max force`：按分段最大力确定骨架点

勾选 `Mark skeleton points` 后，试验曲线图会用红色点标出骨架点。

`Skeleton weight` 控制骨架点 RMSE 在总适应度中的权重。取值范围为 0 到 1，步长为 0.2。值为 0 时仅使用整条滞回曲线 RMSE。

### 3.3 优化算法

`Algorithm` 可选择：

- `PSO`：Particle Swarm Optimization（粒子群优化算法）
- `GA`：Genetic Algorithm（遗传算法）

点击 `Algorithm Parameters...` 设置当前算法的参数。

PSO 参数包括：

- Population size（种群数量）
- Generations（迭代次数）
- Initial inertia（初始惯性权重）
- Final inertia（最终惯性权重）
- Cognitive factor（个体学习因子）
- Social factor（群体学习因子）
- Velocity ratio（速度边界比例）

GA 参数包括：

- Population size（种群数量）
- Generations（迭代次数）
- Crossover rate（交叉概率）
- Mutation rate（变异概率）
- Mutation scale（变异尺度）
- Tournament size（锦标赛选择规模）
- Elite count（精英保留数量）

勾选 `Fixed random seed` 时，程序使用指定随机种子；不勾选时，每次运行使用随机初始化。

菜单栏中的 `Default Algorithm Parameters` 可分别设置 PSO 和 GA 的默认参数。默认参数会保存到系统设置中，下次打开软件时自动加载。

### 3.4 材料定义

材料定义由三部分组成：

1. 固定函数头和参数提取代码
2. 可编辑材料定义代码
3. 固定返回语句

用户只需要编辑中间代码块。按下 `Tab` 会输入 4 个空格。

示例：

```python
    mats = [
        ["Steel01", 1, fy, E0, b],
    ]
    ctrl_tag = 1
```

可以在中间代码块中定义多个 OpenSees 材料。材料编号直接使用从 1 开始的正整数，最终通过 `ctrl_tag` 指定控制材料。程序会自动补齐：

```python
def build(params, context):
    fy = params["fy"]
    E0 = params["E0"]
    b = params["b"]
    ...
    return mats, ctrl_tag
```

### 3.5 材料参数

在 `Material Parameters` 表格中设置每个待识别参数：

- `Name`：参数名，必须是合法 Python 变量名
- `Lower`：参数下界
- `Upper`：参数上界

参数名会自动出现在固定代码区，例如：

```python
fy = params["fy"]
```

## 4. 开始识别

点击 `Start` 开始计算。计算过程中：

- `Stop` 可请求停止计算
- 进度条显示当前迭代进度
- 日志会显示开始时间、算法、OpenSees 模块路径、参数边界和每代最优 RMSE

每次点击 `Start` 都会清空上一轮日志。

识别结束后，程序会自动检查最终参数是否接近上下界。如果某个参数接近边界，会弹出警告，建议调整边界后重新识别。

## 5. 结果页

结果页包含：

- 参数变化图：显示当前参数的每代最优值和全局最优值
- RMSE 图：显示每代最优 RMSE 和全局最优 RMSE
- 滞回曲线对比图：显示试验曲线和当前迭代对应的模拟曲线

拖动 `Generation` 滑块可查看不同迭代下的结果。

## 6. 保存结果

点击 `Save Data...` 选择导出目录。程序会创建形如以下名称的文件夹：

```text
identification_export_YYYYMMDD
```

若同名文件夹已存在，会自动追加 `_2`、`_3`。

导出内容包括：

- `parameter_definitions.json`：计算前所有参数定义
- `final_results.json`：最终识别结果
- `run.log`：运行日志
- `experimental_hysteresis.png`：试验曲线
- `hysteresis_comparison.png`：最终滞回曲线对比
- `rmse_history.png`：RMSE 变化曲线
- `parameter_*.png`：每个材料参数的变化曲线
- `hysteresis_iterations.gif`：不同迭代下模拟曲线与试验曲线的动态对比

保存完成后，程序会弹出提示框。

## 7. 菜单栏

菜单栏包含：

- `User Guide > Chinese`：打开中文用户文档
- `User Guide > English`：打开英文用户文档
- `Default Algorithm Parameters > PSO`：设置并保存 PSO 默认参数
- `Default Algorithm Parameters > GA`：设置并保存 GA 默认参数
- `About`：显示软件信息
- `Exit`：退出程序
