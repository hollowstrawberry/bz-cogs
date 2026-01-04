import asyncio
import discord
import discord.ui as ui
from copy import deepcopy

from aimage.common.constants import ADETAILER_ARGS
from aimage.views.image_actions import ImageActions


class HiresModal(ui.Modal):
    def __init__(self, parent_view: ImageActions, parent_interaction: discord.Interaction, maxsize: int):
        super().__init__(title="Upscale Image")
        assert parent_interaction.guild
        self.parent_view = parent_view
        self.parent_interaction = parent_interaction
        self.parent_button = parent_view.button_upscale
        self.payload = deepcopy(parent_view.payload)
        self.generate_image = parent_view.generate_image

        upscalers = sorted(parent_view.cache[parent_interaction.guild.id].get("upscalers", []))
        maxscale = ((maxsize*maxsize) / (self.payload["width"]*self.payload["height"]))**0.5
        scales = [num/100 for num in range(100, min(max(int(maxscale * 100) + 1, 101), 201), 25)] # 1.00 1.25 1.50 1.75 2.00
        default_scale = 1.5 if 1.5 in scales else scales[-1]
        self.adetailer = "adetailer" in parent_view.cache[parent_interaction.guild.id].get("scripts", [])

        self.upscaler_select = ui.Label(
            text="Upscaler",
            component=ui.Select(options=[
                discord.SelectOption(label=name, default=i==0)
                for i, name in enumerate(upscalers[:25])
            ])
        )
        self.scale_select = ui.Label(
            text="Scale",
            component=ui.Select(options=[
                discord.SelectOption(label=f"x{num:.2f}", value=str(num), default=num==default_scale)
                for num in scales
            ])
        )
        self.denoising_select = ui.Label(
            text="Denoising",
            description="How much the image will change.",
            component=ui.Select(options=[
                discord.SelectOption(label=f"{num / 100:.2f}", value=str(num / 100), default=num == 40)
                for num in range(0, 100, 5)
            ])
        )
        self.adetailer_select = ui.Label(
            text="ADetailer",
            description="Improves small faces.",
            component=ui.Select(options=[
                discord.SelectOption(label="Enabled", value="1", default=True),
                discord.SelectOption(label="Disabled", value="0"),
            ])
        )

        if upscalers:
            self.add_item(self.upscaler_select)
        self.add_item(self.scale_select)
        self.add_item(self.denoising_select)
        if self.adetailer:
            self.add_item(self.adetailer_select)


    async def on_submit(self, interaction: discord.Interaction):
        assert self.parent_interaction.message
        assert isinstance(self.upscaler_select.component, discord.ui.Select)
        assert isinstance(self.scale_select.component, discord.ui.Select)
        assert isinstance(self.denoising_select.component, discord.ui.Select)
        assert isinstance(self.adetailer_select.component, discord.ui.Select)

        self.payload["enable_hr"] = True
        self.payload["hr_upscaler"] = self.upscaler_select.component.values[0]
        self.payload["hr_scale"] = float(self.scale_select.component.values[0])
        self.payload["denoising_strength"] = float(self.denoising_select.component.values[0])
        self.payload["hr_second_pass_steps"] = int(self.payload["steps"]) // 2
        self.payload["hr_prompt"] = self.payload["prompt"]
        self.payload["hr_negative_prompt"] = self.payload["negative_prompt"]
        self.payload["hr_resize_x"] = 0
        self.payload["hr_resize_y"] = 0

        params = self.parent_view.get_params_dict() or {}
        self.payload["seed"] = int(params["Seed"])
        self.payload["subseed"] = int(params.get("Variation seed", -1))
        self.payload["subseed_strength"] = float(params.get("Variation seed strength", 0))

        if self.adetailer and bool(int(self.adetailer_select.component.values[0])):
            self.payload["alwayson_scripts"].update(ADETAILER_ARGS)
        elif "ADetailer" in self.payload["alwayson_scripts"]:
            del self.payload["alwayson_scripts"]["ADetailer"]

        await interaction.response.defer(thinking=True)
        message_content = f"Upscale requested by {interaction.user.mention}"
        await self.generate_image(interaction, payload=self.payload, callback=self.edit_callback(), message_content=message_content)
        
        self.parent_button.disabled = True
        await self.parent_interaction.message.edit(view=self.parent_view)


    async def edit_callback(self):
        await asyncio.sleep(1)
        assert self.parent_interaction.message
        self.parent_button.disabled = False
        if not self.parent_view.is_finished():
            try:
                await self.parent_interaction.message.edit(view=self.parent_view)
            except discord.NotFound:
                pass
