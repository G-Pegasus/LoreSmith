package com.ainovel.platform.interfaces.dto;

import java.util.List;

/**
 * 灵感对话的结构化设定草稿 —— 前端 / Java / 抽取提示词三方共用的唯一契约，同时也是「设定四件套」的定义。
 *
 * <p>字段名刻意使用 {@code StoryCreateForm} 的 state 键名（{@code worldSetting} 而非 {@code premise}、
 * {@code synopsis} 而非 {@code prompt}），这样"填入表单"退化成一次 spread，不需要任何转换层。
 * 角色只保留 {@code name} / {@code role} / {@code description} 三个字段，与 {@code CharacterDraft}、
 * {@code CreateStoryRequest.characters}、Python {@code _seed_story_context} 天然一致 —— 这是下游零改动的前提。</p>
 */
public record InspirationSettingsResponse(
        String title,
        String worldSetting,
        List<CharacterSetting> characters,
        String synopsis
) {
    public record CharacterSetting(String name, String role, String description) {}
}
