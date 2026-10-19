using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;

namespace ArchiveReader;

public static class Localizer
{
    static readonly Dictionary<string, string[]> entries = JsonSerializer.Deserialize<Dictionary<string,string[]>>(File.ReadAllText(System.IO.Path.Combine(AppContext.BaseDirectory,"translations.json")))!;
    static readonly Dictionary<(DependencyObject,string),string> originals = new();
    public static string Language { get; private set; } = "uk";
    public static string Text(string text)
    {
        if(Language=="uk" && new Dictionary<string,string> { ["pending"]="Очікує", ["running"]="Обробка", ["done"]="Готово", ["error"]="Помилка" }.TryGetValue(text,out var status)) return status;
        int index=Array.IndexOf(new[] {"en","pl","cs"},Language);
        return index >= 0 && entries.TryGetValue(text,out var values) ? values[index] : text;
    }
    public static string Format(string text, params object?[] args) => string.Format(Text(text),args);
    public static void Apply(Window window,string language)
    {
        Language=new[] {"uk","en","pl","cs"}.Contains(language) ? language : "uk";
        Visit(window);
    }
    static string Translate(DependencyObject target,string property,string value)
    {
        var key=(target,property);
        if(!originals.TryGetValue(key,out var original)) { originals[key]=value; original=value; }
        return Text(original);
    }
    static void Visit(DependencyObject item)
    {
        if(item is Window window) window.Title=Translate(window,"Title",window.Title);
        if(item is TextBlock block && block.Name!="Status") block.Text=Translate(block,"Text",block.Text);
        if(item is ContentControl content && content.Content is string value) content.Content=Translate(content,"Content",value);
        if(item is HeaderedContentControl header && header.Header is string h) header.Header=Translate(header,"Header",h);
        if(item is FrameworkElement element && element.ToolTip is string tip) element.ToolTip=Translate(element,"ToolTip",tip);
        foreach(var child in LogicalTreeHelper.GetChildren(item).OfType<DependencyObject>()) Visit(child);
    }
}
