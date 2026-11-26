"""Gradio forms shared by the standalone launchers and the hub."""

import gradio as gr

DESCRIPTION = (
    "Zero-shot voice conversion with in-context learning. Reference audio is clipped to 25s; "
    "long sources are processed in chunks. "
    "[Project and documentation](https://github.com/Plachtaa/seed-vc)<br>"
    "无需训练的 zero-shot 语音/歌声转换模型。请注意，参考音频若超过 25 秒，则会被自动裁剪至此长度。"
    "若源音频和参考音频的总时长超过 30 秒，源音频将被分段处理。"
)


def create_interface(key, fn, intro=""):
    style = key == "style"
    titles = {"speech": "Seed Voice Conversion", "singing": "Seed Singing Voice Conversion",
              "style": "Seed Voice Conversion V2"}
    inputs = [
        gr.Audio(type="filepath", label="Source Audio / 源音频"),
        gr.Audio(type="filepath", label="Reference Audio / 参考音频"),
        gr.Slider(1, 200, value=30 if style else 10, step=1, label="Diffusion Steps / 扩散步数",
                  info="50–100 for best quality / 50~100 为最佳质量"),
        gr.Slider(0.5, 2.0, value=1.0, step=0.1, label="Length Adjust / 长度调整",
                  info="<1 speeds up speech, >1 slows it down / <1.0 加速语速，>1.0 减慢语速"),
    ]
    pairs = [
        ("yae_0.wav", "dingzhen_0.wav"),
        ("jay_0.wav", "azuma_0.wav"),
    ]
    if style:
        inputs += [
            gr.Slider(0, 1, value=0.5, step=0.1, label="Intelligibility CFG Rate"),
            gr.Slider(0, 1, value=0.5, step=0.1, label="Similarity CFG Rate"),
            gr.Slider(0.1, 1, value=0.9, step=0.1, label="Top-p", info="Controls sampling diversity / 控制生成音频的多样性"),
            gr.Slider(0.1, 2, value=1.0, step=0.1, label="Temperature", info="Controls randomness / 控制生成音频的随机性"),
            gr.Slider(1, 3, value=1.0, step=0.1, label="Repetition Penalty"),
            gr.Checkbox(label="Convert style / emotion / accent", value=False),
            gr.Checkbox(label="Anonymization only", value=False),
        ]
        settings = [[50, 1.0, 0.5, 0.5, 0.9, 1.0, 1.0, False, False]] * 2
    else:
        inputs.append(gr.Slider(0, 1, value=0.7, step=0.1, label="Inference CFG Rate"))
        settings = [[25, 1.0, 0.7]] * 2
        if key == "singing":
            inputs += [gr.Checkbox(label="Auto F0 adjust / 自动F0调整", value=True),
                       gr.Slider(-24, 24, step=1, value=0, label="Pitch shift / 音调变换",
                                 info="Pitch shift in semitones / 半音数的音高变换")]
            pairs += [("Wiz Khalifa,Charlie Puth - See You Again [vocals]_[cut_28sec].wav", "teio_0.wav"),
                      ("TECHNOPOLIS - 2085 [vocals]_[cut_14sec].wav", "trump_0.wav")]
            settings = [[25, 1.0, 0.7, True, 0], [25, 1.0, 0.7, True, 0],
                        [50, 1.0, 0.7, False, 0], [50, 1.0, 0.7, False, -12]]

    examples = [[f"examples/source/{src}", f"examples/reference/{ref}", *params]
                for (src, ref), params in zip(pairs, settings)]
    outputs = [gr.Audio(label="Stream Output Audio / 流式输出", streaming=True, format="mp3"),
               gr.Audio(label="Full Output Audio / 完整输出", format="wav")]
    return gr.Interface(fn=fn, title=titles[key], description=intro + DESCRIPTION, inputs=inputs,
                        outputs=outputs, examples=examples, cache_examples=False)
