from copy import copy

import discord

from aimage.views.image_actions import ImageActions

class VariationView(discord.ui.View):
    def __init__(self, parent: ImageActions, interaction: discord.Interaction):
        super().__init__()
        self.src_view = parent
        self.src_interaction = interaction
        self.src_button = parent.button_variation
        self.payload = copy(parent.payload)
        self.generate_image = parent.generate_image
        self.strength = 0.05
        self.add_item(VariationStrengthSelect(self))

    @discord.ui.button(emoji='🤏', label='Make Variation', style=discord.ButtonStyle.blurple, row=2)
    async def makevariation(self, interaction: discord.Interaction, _: discord.Button):
        await interaction.response.defer(thinking=True)
        self.payload["subseed"] = -1
        self.payload["subseed_strength"] = self.strength

        self.src_button.disabled = True
        await self.src_interaction.message.edit(view=self.src_view)
        await self.src_interaction.delete_original_response()
        await self.generate_image(interaction, payload=self.payload)

        self.src_button.disabled = False
        if not self.src_view.is_finished():
            try:
                await self.src_interaction.message.edit(view=self.src_view)
            except:
                pass


class VariationStrengthSelect(discord.ui.Select):
    def __init__(self, parent: VariationView,):
        self.parent = parent
        options = [discord.SelectOption(label=f"{num}%", value=str(num)) for num in range(1, 21)]
        options[4].default = True
        super().__init__(options=options)

    async def callback(self, interaction: discord.Interaction):
        self.parent.strength = float(self.values[0]) / 100
        for option in self.options:
            option.default = option.value == self.values[0]
        await interaction.response.edit_message(view=self.parent)
