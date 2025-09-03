import discord

from aimage.views.image_actions import ImageActions


class PromptModal(discord.ui.Modal):
    def __init__(self, parent: ImageActions, interaction: discord.Interaction, prompt: str, negative_prompt: str):
        self.src_view = parent
        self.src_interaction = interaction
        self.title = "Modify Prompt"
        self.add_item(discord.ui.TextInput(label="Prompt", default=prompt, placeholder=prompt, min_length=4))
        self.add_item(discord.ui.TextInput(label="Negative Prompt", default=negative_prompt, placeholder=negative_prompt, min_length=4))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("success", ephemeral=True)